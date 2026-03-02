"""
gallery_worker.py — Worker for gallery-dl supported sites (priority 30).

Handles: Instagram, Reddit, Imgur, DeviantArt, Pixiv, Flickr, etc.
Strategy: gallery-dl subprocess (handles image galleries / multi-image posts
          that yt-dlp can't handle well).

AI-MAINTENANCE NOTE:
  gallery-dl config lives at ~/.config/gallery-dl/config.json (or %APPDATA%/gallery-dl/)
  If a site needs authentication, add cookies/config there — don't hardcode credentials.
  Check 'gallery-dl --list-extractors' to see supported sites.
"""
from __future__ import annotations

import subprocess
import traceback
from pathlib import Path

from mmi.config import get_logger
from mmi.engine.base import BaseWorker, IngestionResult

logger = get_logger("mmi.gallery")

# Sites that gallery-dl handles better than yt-dlp
# This is a curated list — gallery-dl supports many more.
# AI-MAINTENANCE: Extend this list as needed; each entry is a partial host match.
_GALLERY_HOSTS = (
    "instagram.com",
    "reddit.com",
    "imgur.com",
    "deviantart.com",
    "pixiv.net",
    "flickr.com",
    "twitter.com",   # For image tweets (yt-dlp handles video tweets — priority 40)
    "x.com",         # Twitter's current domain
    "artstation.com",
    "danbooru.donmai.us",
    "gelbooru.com",
)


class GalleryWorker(BaseWorker):
    priority = 30

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _GALLERY_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "gallery-dl",
            "--dest", str(output_dir),
            "--no-mtime",
            url,
        ]
        logger.debug("Running: %s", " ".join(cmd))

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
                url=url,
                worker_name=type(self).__name__,
                error_code="GALLERY_DL_NOT_FOUND",
                error_message="gallery-dl executable not found. Install with: pip install gallery-dl",
            )
        except Exception as exc:  # noqa: BLE001
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="SUBPROCESS_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            logger.debug("gallery-dl stderr: %s", stderr)
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code=str(result.returncode),
                error_message=stderr or f"gallery-dl exited with code {result.returncode}",
            )

        # gallery-dl prints downloaded filenames to stdout, one per line
        downloaded_files = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        filename = downloaded_files[-1] if downloaded_files else None

        return IngestionResult(
            success=True,
            url=url,
            worker_name=type(self).__name__,
            filename=filename,
            metadata={"files_downloaded": len(downloaded_files)},
        )
