"""
custom_worker.py — Manual m3u8 stream download worker.

This worker is NEVER auto-routed. It is invoked explicitly via:
  mmi --m3u8 <stream_url> --referer <page_url>

can_handle() always returns False to prevent accidental inclusion in the
priority chain.

AI-MAINTENANCE NOTE:
  m3u8 streams sometimes require custom headers beyond Referer (e.g. Origin,
  Cookie). Extend the ffmpeg command's -headers string if needed.
"""
from __future__ import annotations

import subprocess
import traceback
from pathlib import Path
from urllib.parse import urlparse

from mmi.config import CHROME_USER_AGENT, get_logger
from mmi.engine.base import BaseWorker, IngestionResult

logger = get_logger("mmi.custom")


class CustomWorker(BaseWorker):
    """Manual m3u8 override — never participates in auto-routing."""

    priority = 0  # Irrelevant since can_handle always returns False

    def can_handle(self, url: str) -> bool:
        # Always False — only invoked explicitly via CLI --m3u8 flag
        return False

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        """Not used in normal flow; raises to alert misuse."""
        raise NotImplementedError(
            "CustomWorker.download() should not be called directly. "
            "Use safe_download_m3u8(stream_url, referer, output_dir) instead."
        )

    def safe_download_m3u8(
        self,
        stream_url: str,
        referer: str,
        output_dir: Path,
    ) -> IngestionResult:
        """
        Download an m3u8 HLS stream using ffmpeg.

        Args:
            stream_url: The .m3u8 playlist URL.
            referer:    The page URL to send as HTTP Referer header.
            output_dir: Directory to save the output file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Derive a filename from the referer page title (safe fallback: 'stream')
        slug = _url_to_slug(referer) or "stream"
        output_file = output_dir / f"{slug}.mp4"

        # Ensure we don't silently overwrite
        output_file = _unique_path(output_file)

        headers = (
            f"Referer: {referer}\r\n"
            f"User-Agent: {CHROME_USER_AGENT}\r\n"
        )

        cmd = [
            "ffmpeg",
            "-headers", headers,
            "-i", stream_url,
            "-c", "copy",          # Stream copy — no re-encode
            "-bsf:a", "aac_adtstoasc",
            str(output_file),
            "-y",                  # Overwrite if file somehow already exists
        ]
        logger.debug("Running ffmpeg: %s", " ".join(cmd[:6]) + " ...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return IngestionResult(
                success=False,
                url=stream_url,
                worker_name=type(self).__name__,
                error_code="FFMPEG_NOT_FOUND",
                error_message="ffmpeg not found. Install from https://ffmpeg.org/download.html",
            )
        except Exception as exc:  # noqa: BLE001
            return IngestionResult(
                success=False,
                url=stream_url,
                worker_name=type(self).__name__,
                error_code="SUBPROCESS_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

        if result.returncode != 0:
            return IngestionResult(
                success=False,
                url=stream_url,
                worker_name=type(self).__name__,
                error_code=str(result.returncode),
                error_message=result.stderr[-2000:] if result.stderr else "ffmpeg failed",
            )

        return IngestionResult(
            success=True,
            url=stream_url,
            worker_name=type(self).__name__,
            filename=str(output_file),
        )


def _url_to_slug(url: str, max_len: int = 60) -> str:
    """Convert a URL into a safe filename slug."""
    import re
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
    slug = re.sub(r"[^\w\-]", "_", path)
    return slug[:max_len]


def _unique_path(path: Path) -> Path:
    """Append a counter suffix if path already exists."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
