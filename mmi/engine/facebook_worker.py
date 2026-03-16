"""
facebook_worker.py — Stealth Facebook video download worker (priority 35).

Handles: facebook.com, fb.watch
Strategy: Tor-routed Playwright with full fingerprint spoofing, seeded cookie
          history, and human-like timing. Each download gets a fresh Tor circuit
          + fresh randomized browser profile.

Falls in BEFORE YtdlpWorker (priority 40) — stealth is the default path for all
Facebook downloads. YtdlpWorker acts as fallback if stealth fails.

Intercepted CDN pattern: *.fbcdn.net (Facebook's video delivery network).
Falls back to any .mp4 URL on the page if fbcdn is not found.

Instagram fallback: FB Shorts that originate from Instagram won't expose a CDN
stream. When no stream is intercepted, the worker scrapes the page for Instagram
reel/post URLs and re-ingests via mmi.ingest() (routes to GalleryWorker).

AI-MAINTENANCE NOTE:
  If Facebook changes its CDN domain, add it to _FB_CDN_HINTS.
  Tor binary location: set MMI_TOR_BUNDLE_DIR env var (see mmi/tor_pool.py).
  Tor must be available: either already running on port 9050, or
  tor.exe must exist in the MMI_TOR_BUNDLE_DIR/tor/ directory.
"""
from __future__ import annotations

import re
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

logger = get_logger("mmi.facebook")

_FACEBOOK_HOSTS = ("facebook.com", "fb.watch")

# Facebook's video CDN — intercept any request to these domains
_FB_CDN_HINTS = (
    "fbcdn.net",
    "video.xx.fbcdn.net",
    "video-",       # Facebook video segment prefix pattern
)

# Regex to find Instagram reel/post URLs in page content
_INSTAGRAM_URL_RE = re.compile(
    r'https?://(?:www\.)?instagram\.com/(?:reel|p|reels)/[A-Za-z0-9_-]+/?',
)

# Stream manifest patterns
_STREAM_PATTERNS = (".m3u8", ".mpd")

# How long to wait for the video player to fire its CDN request
_INTERCEPT_TIMEOUT_SEC = 25

# Facebook-Monitor config path — Tor settings (socks_port, control_port, etc.)
# Gracefully falls back to safe defaults if not found.
_FB_MONITOR_CONFIG = Path("E:/0-Automated-Apps/Facebook-Monitor/config.json")


def _tor_is_running(host: str = "127.0.0.1", port: int = 9050) -> bool:
    """Check if a Tor SOCKS proxy is already accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


class FacebookWorker(BaseWorker):
    """
    Stealth Facebook video worker.
    Routes through Tor, uses a fresh randomized browser fingerprint per download.
    """

    priority = 35  # Before YtdlpWorker (40) — stealth is the default Facebook path

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _FACEBOOK_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        stealth = _stealth_mod
        tor_pool_mod = _tor_pool_mod

        # Load Tor settings (falls back to safe defaults if config not found)
        config = _load_fb_monitor_config()

        # Ensure Tor is running — reuse if already up, start if not
        tor_proc = None
        if not _tor_is_running():
            logger.info("Tor not running, starting via configured tor bundle...")
            try:
                tor_proc = tor_pool_mod.ensure_main_tor(config)
                # Wait for bootstrap
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

        # Renew circuit — fresh exit node for this request
        try:
            stealth.renew_tor_circuit(config)
            logger.debug("Tor circuit renewed")
        except Exception as exc:
            logger.warning("Circuit renewal failed (continuing anyway): %s", exc)

        # Intercept video URL via stealth browser
        try:
            stream_url, stream_type, instagram_url = self._intercept_with_stealth(
                url, stealth, config
            )
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
            # ── Instagram fallback ────────────────────────────────────────
            # FB Shorts shared from Instagram won't expose a CDN stream.
            # If we found an Instagram URL on the page, re-ingest via MMI
            # which routes to GalleryWorker (gallery-dl) for Instagram.
            if instagram_url:
                logger.info(
                    "No FB stream found — detected Instagram origin: %s → %s",
                    url, instagram_url,
                )
                try:
                    import mmi
                    ig_result = mmi.ingest(instagram_url, output_dir=output_dir)
                    if ig_result.success:
                        logger.info(
                            "Instagram fallback succeeded via %s",
                            ig_result.worker_name,
                        )
                        # Preserve the original FB URL in metadata
                        ig_result.metadata = ig_result.metadata or {}
                        ig_result.metadata["original_facebook_url"] = url
                        ig_result.metadata["instagram_fallback"] = True
                        ig_result.worker_name = f"{type(self).__name__}→{ig_result.worker_name}"
                        return ig_result
                    else:
                        logger.warning(
                            "Instagram fallback also failed: %s — %s",
                            ig_result.error_code, ig_result.error_message,
                        )
                except Exception as exc:
                    logger.warning("Instagram fallback raised: %s", exc)

            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="NO_STREAM_FOUND",
                error_message=(
                    f"Stealth browser opened the page but no Facebook video CDN "
                    f"request was intercepted within {_INTERCEPT_TIMEOUT_SEC}s."
                    + (f" Instagram URL detected ({instagram_url}) but fallback "
                       f"download also failed." if instagram_url else "")
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
    ) -> tuple[str | None, str | None, str | None]:
        """
        Open url in a stealth Tor-routed Chromium, intercept the video CDN request.
        Each call = fresh browser profile + fresh Tor circuit.

        Returns:
            (stream_url, stream_type, instagram_url)
            - stream_url/stream_type are set when a Facebook CDN video is found
            - instagram_url is set when no stream is found but the page references
              an Instagram reel/post (FB Shorts shared from Instagram)
        """
        from playwright.sync_api import sync_playwright

        found: dict = {}
        done = Event()

        def on_request(request):
            if done.is_set():
                return
            req_url = request.url
            # HLS/DASH manifest
            for pat in _STREAM_PATTERNS:
                if pat in req_url:
                    found["url"] = req_url
                    found["type"] = "m3u8"
                    done.set()
                    return
            # Facebook CDN direct video
            if ".mp4" in req_url and any(hint in req_url for hint in _FB_CDN_HINTS):
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

            # Fresh randomized fingerprint — new identity per request
            context = stealth.create_stealth_context(
                browser, config, proxy_override=proxy
            )
            stealth.seed_browser_history(context)

            page = context.new_page()
            page.on("request", on_request)

            # Warm up first (builds referrer chain, looks human)
            logger.debug("Warming up browser before Facebook navigation...")
            try:
                stealth.warm_up_browser(page)
            except Exception as exc:
                logger.debug("Warm-up partial error (continuing): %s", exc)

            # Navigate to Facebook with human-like timing
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
                    // Also click any play buttons
                    const playBtns = document.querySelectorAll('[data-testid="UFI2ReactionsCount/root"], [aria-label="Play"]');
                    playBtns.forEach(b => b.click());
                """)
            except Exception:
                pass

            done.wait(timeout=_INTERCEPT_TIMEOUT_SEC)

            # If no stream found, check if this is an Instagram reel shared to FB
            instagram_url = None
            if not found.get("url"):
                instagram_url = self._detect_instagram_url(page)

            page.close()
            context.close()
            browser.close()

        return found.get("url"), found.get("type"), instagram_url

    def _detect_instagram_url(self, page) -> str | None:
        """
        Scrape the current FB page for Instagram reel/post URLs.

        FB Shorts that originate from Instagram often contain a link or
        attribution back to the original Instagram post. This method checks:
          1. All <a> href attributes on the page
          2. Page HTML source for instagram.com/reel/ or /p/ patterns
          3. Meta tags (og:url, og:see_also) that reference Instagram
        """
        try:
            # Strategy 1: Check all links on the page
            hrefs = page.evaluate("""
                Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(h => h.includes('instagram.com'))
            """)
            for href in (hrefs or []):
                match = _INSTAGRAM_URL_RE.search(href)
                if match:
                    logger.info("Found Instagram link in page <a> tags: %s", match.group(0))
                    return match.group(0)

            # Strategy 2: Check meta tags
            meta_urls = page.evaluate("""
                Array.from(document.querySelectorAll('meta[content]'))
                    .map(m => m.content)
                    .filter(c => c.includes('instagram.com'))
            """)
            for content in (meta_urls or []):
                match = _INSTAGRAM_URL_RE.search(content)
                if match:
                    logger.info("Found Instagram URL in meta tags: %s", match.group(0))
                    return match.group(0)

            # Strategy 3: Search full page HTML as last resort
            html = page.content()
            match = _INSTAGRAM_URL_RE.search(html)
            if match:
                logger.info("Found Instagram URL in page HTML: %s", match.group(0))
                return match.group(0)

        except Exception as exc:
            logger.debug("Instagram URL detection failed: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    def _download_m3u8(self, stream_url: str, referer: str, output_dir: Path) -> IngestionResult:
        from mmi.config import CHROME_USER_AGENT
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = _url_to_slug(referer) or "facebook_video"
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
        filename = parsed.path.split("/")[-1].split("?")[0] or "facebook_video.mp4"
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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _load_fb_monitor_config() -> dict:
    """Load Tor config from Facebook-Monitor's config.json, or return safe defaults."""
    import json
    config_path = _FB_MONITOR_CONFIG
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Minimal defaults if config.json is missing
    return {
        "tor": {
            "enabled": True,
            "socks_port": 9050,
            "control_port": 9051,
            "control_password": "",
        }
    }


def _wait_for_tor(timeout: int = 90) -> bool:
    """Poll until Tor SOCKS port accepts connections, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _tor_is_running():
            logger.info("Tor bootstrap complete")
            return True
        time.sleep(3)
    logger.warning("Tor did not bootstrap within %ds", timeout)
    return False
