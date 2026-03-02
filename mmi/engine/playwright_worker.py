"""
playwright_worker.py — Playwright-based media extraction worker (priority 85).

Handles sites that block yt-dlp with Cloudflare or similar bot protection.
Strategy: open the page in a real Chromium browser, intercept the network
requests the video player makes, capture the m3u8/mp4 URL, and download it.

This works because Playwright runs a genuine browser — Cloudflare challenges
pass, JS executes, and the video player requests its stream as normal.
We simply listen and grab the URL before downloading via ffmpeg or httpx.

Currently targets: rumble.com, rmbl.ws
Add hosts to _PLAYWRIGHT_HOSTS to enable for other sites.

AI-MAINTENANCE NOTE:
  If a site moves from m3u8 to DASH (mpd), add ".mpd" to _STREAM_PATTERNS.
  If the CDN domain changes, add it to _CDN_HINTS.
  Playwright must be installed: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import subprocess
import time
import traceback
from pathlib import Path
from threading import Event

from mmi.config import CHROME_USER_AGENT, get_logger
from mmi.engine.base import BaseWorker, IngestionResult
from mmi.engine.custom_worker import _unique_path, _url_to_slug

logger = get_logger("mmi.playwright")

# Sites that need real-browser extraction
_PLAYWRIGHT_HOSTS = ("rumble.com", "rmbl.ws")

# URL patterns that indicate a media stream manifest
_STREAM_PATTERNS = (".m3u8", ".mpd")

# CDN domain hints for direct mp4 detection (avoids catching thumbnail/ad mp4s)
_CDN_HINTS = (
    "1a-1791.com",
    "cdn.rumble.cloud",
    "rumble.com/video",
)

# How long to wait for the video player to fire its first media request
_INTERCEPT_TIMEOUT_SEC = 20


class PlaywrightWorker(BaseWorker):
    """
    Real-browser worker. Falls in after all yt-dlp workers have tried.
    Intercepts media network requests from the page's own video player.
    """

    priority = 85  # After YtdlpWorker(40), before GenericWorker(100)

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _PLAYWRIGHT_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        logger.info("Launching Playwright for %s", url)

        try:
            stream_url, stream_type = self._intercept_media(url)
        except ImportError:
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="PLAYWRIGHT_NOT_INSTALLED",
                error_message="playwright not installed. Run: pip install playwright && playwright install chromium",
            )
        except Exception as exc:
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="PLAYWRIGHT_ERROR",
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
                    f"Playwright opened the page but no media URL was intercepted "
                    f"within {_INTERCEPT_TIMEOUT_SEC}s. The player may require interaction."
                ),
            )

        logger.info("Intercepted %s: %s", stream_type, stream_url)

        if stream_type == "m3u8":
            return self._download_m3u8(stream_url, referer=url, output_dir=output_dir)
        else:
            return self._download_direct(stream_url, referer=url, output_dir=output_dir)

    # ------------------------------------------------------------------
    # Browser interception
    # ------------------------------------------------------------------

    def _intercept_media(self, page_url: str) -> tuple[str | None, str | None]:
        """
        Open page_url in a headless Chromium, intercept the first media request.

        Returns:
            (stream_url, stream_type) where stream_type is 'm3u8' or 'direct',
            or (None, None) if nothing was found within the timeout.
        """
        from playwright.sync_api import sync_playwright

        found: dict = {}
        done = Event()

        def on_request(request):
            if done.is_set():
                return
            req_url = request.url
            # HLS/DASH manifest — highest priority
            for pat in _STREAM_PATTERNS:
                if pat in req_url:
                    found["url"] = req_url
                    found["type"] = "m3u8"
                    done.set()
                    return
            # Direct CDN mp4 — only if it looks like a real video CDN
            if ".mp4" in req_url and any(cdn in req_url for cdn in _CDN_HINTS):
                found["url"] = req_url
                found["type"] = "direct"
                done.set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )
            context = browser.new_context(
                user_agent=CHROME_USER_AGENT,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = context.new_page()
            page.on("request", on_request)

            try:
                page.goto(page_url, wait_until="domcontentloaded", timeout=25_000)
            except Exception as exc:
                logger.debug("goto partial error (may be fine): %s", exc)

            # Unmute and trigger autoplay on any video element
            try:
                page.evaluate("""
                    const videos = document.querySelectorAll('video');
                    videos.forEach(v => { v.muted = true; v.play().catch(() => {}); });
                """)
            except Exception:
                pass

            # Give the player time to boot and fire its first media request
            done.wait(timeout=_INTERCEPT_TIMEOUT_SEC)
            browser.close()

        return found.get("url"), found.get("type")

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    def _download_m3u8(self, stream_url: str, referer: str, output_dir: Path) -> IngestionResult:
        """Stitch an HLS stream to a single mp4 via ffmpeg."""
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = _url_to_slug(referer) or "stream"
        output_file = _unique_path(output_dir / f"{slug}.mp4")

        headers = (
            f"Referer: {referer}\r\n"
            f"User-Agent: {CHROME_USER_AGENT}\r\n"
        )
        cmd = [
            "ffmpeg",
            "-headers", headers,
            "-i", stream_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            str(output_file),
            "-y",
        ]
        logger.debug("ffmpeg: %s", " ".join(cmd[:6]) + " ...")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            return IngestionResult(
                success=False,
                url=referer,
                worker_name=type(self).__name__,
                error_code="FFMPEG_NOT_FOUND",
                error_message="ffmpeg not found. Install from https://ffmpeg.org/download.html",
            )
        except Exception as exc:
            return IngestionResult(
                success=False,
                url=referer,
                worker_name=type(self).__name__,
                error_code="SUBPROCESS_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

        if result.returncode != 0:
            return IngestionResult(
                success=False,
                url=referer,
                worker_name=type(self).__name__,
                error_code=str(result.returncode),
                error_message=result.stderr[-2000:] if result.stderr else "ffmpeg failed",
            )

        return IngestionResult(
            success=True,
            url=referer,
            worker_name=type(self).__name__,
            filename=str(output_file),
            metadata={"stream_url": stream_url},
        )

    def _download_direct(self, stream_url: str, referer: str, output_dir: Path) -> IngestionResult:
        """Download a direct CDN mp4 via httpx."""
        import httpx
        from urllib.parse import urlparse

        output_dir.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(stream_url)
        filename = parsed.path.split("/")[-1] or "video.mp4"
        if "." not in filename:
            filename += ".mp4"
        output_file = _unique_path(output_dir / filename)

        try:
            headers = {"User-Agent": CHROME_USER_AGENT, "Referer": referer}
            with httpx.stream(
                "GET", stream_url, headers=headers, follow_redirects=True, timeout=60
            ) as resp:
                resp.raise_for_status()
                with open(output_file, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
        except Exception as exc:
            return IngestionResult(
                success=False,
                url=referer,
                worker_name=type(self).__name__,
                error_code="DIRECT_DOWNLOAD_FAILED",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

        return IngestionResult(
            success=True,
            url=referer,
            worker_name=type(self).__name__,
            filename=str(output_file),
            metadata={"stream_url": stream_url},
        )
