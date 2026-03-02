"""
rumble_stealth_worker.py — Stealth Tor+Playwright fallback for Rumble (priority 87).

Handles: rumble.com, rmbl.ws
Strategy: Tor-routed Playwright with full fingerprint spoofing. This is the last
          resort before GenericWorker — it kicks in only when both yt-dlp
          (RumbleWorker) and plain headless Chromium (PlaywrightWorker) have failed.

Why Tor? Cloudflare bans are IP-level. A fresh Tor exit node presents a different IP,
bypassing the block even when the browser fingerprint alone is insufficient.

Falls in AFTER PlaywrightWorker (priority 85) and BEFORE GenericWorker (100).

AI-MAINTENANCE NOTE:
  If Rumble's CDN domain changes, update _CDN_HINTS (keep in sync with playwright_worker.py).
  Tor binary location: set MMI_TOR_BUNDLE_DIR env var (see mmi/tor_pool.py).
  Tor must be available: either already running on port 9050, or
  tor.exe must exist in the MMI_TOR_BUNDLE_DIR/tor/ directory.
"""
from __future__ import annotations

import socket
import subprocess
import time
import traceback
from pathlib import Path
from threading import Event

from mmi import stealth as _stealth_mod
from mmi import tor_pool as _tor_pool_mod
from mmi.config import get_logger
from mmi.engine.base import BaseWorker, IngestionResult
from mmi.engine.custom_worker import _unique_path, _url_to_slug

logger = get_logger("mmi.rumble_stealth")

_RUMBLE_HOSTS = ("rumble.com", "rmbl.ws")

# CDN domains / URL patterns that mean we found the real video — keep in sync with
# playwright_worker.py _CDN_HINTS
_CDN_HINTS = (
    "1a-1791.com",
    "cdn.rumble.cloud",
    "rumble.com/video",
)

_STREAM_PATTERNS = (".m3u8", ".mpd")

_INTERCEPT_TIMEOUT_SEC = 30  # longer than PlaywrightWorker (20s) — Tor adds latency

# Tor config path — gracefully falls back to safe defaults if not found
_FB_MONITOR_CONFIG = Path("E:/0-Automated-Apps/Facebook-Monitor/config.json")


def _tor_is_running(host: str = "127.0.0.1", port: int = 9050) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def _load_fb_monitor_config() -> dict:
    import json
    if _FB_MONITOR_CONFIG.exists():
        try:
            return json.loads(_FB_MONITOR_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "tor": {
            "enabled": True,
            "socks_port": 9050,
            "control_port": 9051,
            "control_password": "",
        }
    }


def _wait_for_tor(timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _tor_is_running():
            logger.info("Tor bootstrap complete")
            return True
        time.sleep(3)
    logger.warning("Tor did not bootstrap within %ds", timeout)
    return False


class RumbleStealthWorker(BaseWorker):
    """
    Stealth Tor+Playwright fallback for Rumble.
    Only reached after both RumbleWorker (yt-dlp) and PlaywrightWorker (plain Chromium) fail.
    """

    priority = 87  # After PlaywrightWorker (85), before GenericWorker (100)

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _RUMBLE_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        stealth = _stealth_mod
        tor_pool_mod = _tor_pool_mod

        config = _load_fb_monitor_config()

        if not _tor_is_running():
            logger.info("Tor not running, starting via configured tor bundle...")
            try:
                tor_pool_mod.ensure_main_tor(config)
                _wait_for_tor(timeout=90)
            except Exception as exc:
                return IngestionResult(
                    success=False,
                    url=url,
                    worker_name=type(self).__name__,
                    error_code="TOR_START_FAILED",
                    error_message=str(exc),
                    stack_trace=traceback.format_exc(),
                )
        else:
            logger.info("Tor already running on port 9050, reusing")

        try:
            stealth.renew_tor_circuit(config)
            logger.debug("Tor circuit renewed")
        except Exception as exc:
            logger.warning("Circuit renewal failed (continuing anyway): %s", exc)

        try:
            stream_url, stream_type = self._intercept_with_stealth(url, stealth, config)
        except Exception as exc:
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="STEALTH_BROWSE_FAILED",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

        if not stream_url:
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="NO_STREAM_FOUND",
                error_message=(
                    f"Stealth browser opened the page but no Rumble CDN request was "
                    f"intercepted within {_INTERCEPT_TIMEOUT_SEC}s."
                ),
            )

        logger.info("Intercepted %s: %s", stream_type, stream_url[:80])

        if stream_type == "m3u8":
            return self._download_m3u8(stream_url, referer=url, output_dir=output_dir)
        else:
            return self._download_direct(stream_url, referer=url, output_dir=output_dir)

    # ------------------------------------------------------------------
    # Stealth browser interception
    # ------------------------------------------------------------------

    def _intercept_with_stealth(
        self, url: str, stealth, config: dict
    ) -> tuple[str | None, str | None]:
        from playwright.sync_api import sync_playwright

        found: dict = {}
        done = Event()

        def on_request(request):
            if done.is_set():
                return
            req_url = request.url
            for pat in _STREAM_PATTERNS:
                if pat in req_url:
                    found["url"] = req_url
                    found["type"] = "m3u8"
                    done.set()
                    return
            if ".mp4" in req_url and any(hint in req_url for hint in _CDN_HINTS):
                found["url"] = req_url
                found["type"] = "direct"
                done.set()

        proxy = stealth.get_tor_proxy(config)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                proxy=proxy,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )

            context = stealth.create_stealth_context(
                browser, config, proxy_override=proxy
            )
            stealth.seed_browser_history(context)

            page = context.new_page()
            page.on("request", on_request)

            logger.debug("Warming up browser before Rumble navigation...")
            try:
                stealth.warm_up_browser(page)
            except Exception as exc:
                logger.debug("Warm-up partial error (continuing): %s", exc)

            logger.debug("Navigating to %s", url)
            try:
                stealth.stealth_goto(page, url)
            except Exception as exc:
                logger.debug("stealth_goto partial error (continuing): %s", exc)

            # Trigger video autoplay
            try:
                page.evaluate("""
                    const videos = document.querySelectorAll('video');
                    videos.forEach(v => { v.muted = true; v.play().catch(() => {}); });
                """)
            except Exception:
                pass

            done.wait(timeout=_INTERCEPT_TIMEOUT_SEC)

            page.close()
            context.close()
            browser.close()

        return found.get("url"), found.get("type")

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    def _download_m3u8(self, stream_url: str, referer: str, output_dir: Path) -> IngestionResult:
        from mmi.config import CHROME_USER_AGENT
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = _url_to_slug(referer) or "rumble_video"
        output_file = _unique_path(output_dir / f"{slug}.mp4")

        headers = f"Referer: {referer}\r\nUser-Agent: {CHROME_USER_AGENT}\r\n"
        cmd = [
            "ffmpeg", "-headers", headers,
            "-i", stream_url,
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            str(output_file), "-y",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            return IngestionResult(
                success=False, url=referer, worker_name=type(self).__name__,
                error_code="FFMPEG_NOT_FOUND",
                error_message="ffmpeg not found. Install from https://ffmpeg.org/download.html",
            )
        except Exception as exc:
            return IngestionResult(
                success=False, url=referer, worker_name=type(self).__name__,
                error_code="SUBPROCESS_ERROR", error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

        if result.returncode != 0:
            return IngestionResult(
                success=False, url=referer, worker_name=type(self).__name__,
                error_code=str(result.returncode),
                error_message=result.stderr[-2000:] if result.stderr else "ffmpeg failed",
            )
        return IngestionResult(
            success=True, url=referer, worker_name=type(self).__name__,
            filename=str(output_file),
            metadata={"stream_url": stream_url},
        )

    def _download_direct(self, stream_url: str, referer: str, output_dir: Path) -> IngestionResult:
        import httpx
        from urllib.parse import urlparse
        from mmi.config import CHROME_USER_AGENT

        output_dir.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(stream_url)
        filename = parsed.path.split("/")[-1].split("?")[0] or "rumble_video.mp4"
        if "." not in filename:
            filename += ".mp4"
        output_file = _unique_path(output_dir / filename)

        try:
            headers = {"User-Agent": CHROME_USER_AGENT, "Referer": referer}
            with httpx.stream(
                "GET", stream_url, headers=headers, follow_redirects=True, timeout=120
            ) as resp:
                resp.raise_for_status()
                with open(output_file, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
        except Exception as exc:
            return IngestionResult(
                success=False, url=referer, worker_name=type(self).__name__,
                error_code="DIRECT_DOWNLOAD_FAILED", error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )
        return IngestionResult(
            success=True, url=referer, worker_name=type(self).__name__,
            filename=str(output_file),
            metadata={"stream_url": stream_url},
        )
