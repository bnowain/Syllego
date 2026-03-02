"""
rumble_worker.py — Worker for Rumble video downloads (priority 10).

Handles: rumble.com, rmbl.ws
Strategy: yt-dlp, optionally with a cookies.txt file if one has been harvested.

AI-MAINTENANCE NOTE:
  Rumble returns 403 without cookies. Run `python -m mmi.cookie_harvest` (or
  `mmi --harvest-cookies`) to populate MMI_OUTPUT_DIR/cookies.txt, then retry.
  Check: yt-dlp -F <rumble_url> to see available formats.
"""
from __future__ import annotations

from pathlib import Path

from mmi.config import MMI_OUTPUT_DIR
from mmi.engine._ytdlp_common import run_ytdlp
from mmi.engine.base import BaseWorker, IngestionResult

_RUMBLE_HOSTS = ("rumble.com", "rmbl.ws")


class RumbleWorker(BaseWorker):
    priority = 10

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _RUMBLE_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        extra_args: list[str] | None = None

        cookies_file = MMI_OUTPUT_DIR / "cookies.txt"
        if cookies_file.exists():
            extra_args = ["--cookies", str(cookies_file)]

        return run_ytdlp(
            url=url,
            output_dir=output_dir,
            worker_name=type(self).__name__,
            extra_args=extra_args,
        )
