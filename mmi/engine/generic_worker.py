"""
generic_worker.py — Catch-all fallback worker (priority 100).

Handles: everything that no other worker claimed.
Strategy: yt-dlp with generic extractor, no site-specific flags.
          If yt-dlp fails, tries httpx direct download as last resort.

AI-MAINTENANCE NOTE:
  This worker should remain a catch-all. Don't restrict can_handle() here.
  If a site consistently fails here, create a dedicated worker for it
  (e.g., mysite_worker.py with priority 35) and add it to router._import_workers().
"""
from __future__ import annotations

import traceback
from pathlib import Path
from urllib.parse import urlparse

from mmi.config import CHROME_USER_AGENT, get_logger
from mmi.engine._ytdlp_common import run_ytdlp
from mmi.engine.base import BaseWorker, IngestionResult

logger = get_logger("mmi.generic")


class GenericWorker(BaseWorker):
    priority = 100  # Lowest priority — last resort

    def can_handle(self, url: str) -> bool:
        # Handles everything — true catch-all
        return True

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        # First attempt: yt-dlp generic extractor
        result = run_ytdlp(
            url=url,
            output_dir=output_dir,
            worker_name=type(self).__name__,
            extra_args=["--no-check-certificate"],
        )
        if result.success:
            return result

        logger.debug("yt-dlp failed for generic URL, trying httpx direct download")
        # Second attempt: direct file download via httpx
        return self._direct_download(url, output_dir)

    def _direct_download(self, url: str, output_dir: Path) -> IngestionResult:
        """
        Last-resort: stream the URL directly to a file using httpx.
        Works for direct file links (.mp4, .pdf, .zip, etc.)
        """
        try:
            import httpx
        except ImportError:
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="HTTPX_NOT_FOUND",
                error_message="httpx not installed. Run: pip install httpx",
            )

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            parsed = urlparse(url)
            filename = parsed.path.split("/")[-1] or "download"
            if "." not in filename:
                filename += ".bin"
            output_file = output_dir / filename

            headers = {"User-Agent": CHROME_USER_AGENT}

            with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=30) as resp:
                resp.raise_for_status()
                with open(output_file, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)

            return IngestionResult(
                success=True,
                url=url,
                worker_name=type(self).__name__,
                filename=str(output_file),
                metadata={"method": "httpx_direct"},
            )
        except Exception as exc:  # noqa: BLE001
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="DIRECT_DOWNLOAD_FAILED",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )
