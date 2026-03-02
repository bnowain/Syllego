"""
rumble_worker.py — Worker for Rumble video downloads (priority 10).

Handles: rumble.com, rmbl.ws
Strategy: yt-dlp with no extra flags (Rumble is natively supported).

AI-MAINTENANCE NOTE:
  If Rumble starts requiring cookies or a different extractor, add flags to
  `extra_args` below. Check: yt-dlp -F <rumble_url> to see available formats.
"""
from __future__ import annotations

from pathlib import Path

from mmi.engine._ytdlp_common import run_ytdlp
from mmi.engine.base import BaseWorker, IngestionResult

_RUMBLE_HOSTS = ("rumble.com", "rmbl.ws")


class RumbleWorker(BaseWorker):
    priority = 10

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _RUMBLE_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        return run_ytdlp(
            url=url,
            output_dir=output_dir,
            worker_name=type(self).__name__,
            # Rumble works fine with default yt-dlp settings
            extra_args=None,
        )
