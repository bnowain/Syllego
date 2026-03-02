"""
ytdlp_worker.py — Worker for yt-dlp supported sites (priority 40).

Handles: YouTube, Vimeo, TikTok, Facebook, Twitch clips, Twitter videos, etc.
Strategy: yt-dlp with best quality selection.

AI-MAINTENANCE NOTE:
  YouTube rate-limits unauthenticated downloads. If you see 429 errors, try:
    extra_args=["--cookies-from-browser", "chrome", "--sleep-interval", "2"]
  TikTok may need: extra_args=["--cookies-from-browser", "chrome"]
  For age-restricted content: extra_args=["--cookies-from-browser", "chrome"]
"""
from __future__ import annotations

from pathlib import Path

from mmi.engine._ytdlp_common import run_ytdlp
from mmi.engine.base import BaseWorker, IngestionResult

# Sites explicitly handled by this worker (others fall through to GenericWorker)
# yt-dlp supports 1000+ sites — this list just represents common ones.
_YTDLP_HOSTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "tiktok.com",
    "facebook.com",
    "fb.watch",
    "twitch.tv",
    "dailymotion.com",
    "twitter.com",
    "x.com",
    "bilibili.com",
    "soundcloud.com",
    "bandcamp.com",
    "mixcloud.com",
)


class YtdlpWorker(BaseWorker):
    priority = 40

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _YTDLP_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        return run_ytdlp(
            url=url,
            output_dir=output_dir,
            worker_name=type(self).__name__,
            # Best video+audio merged, prefer mp4
            extra_args=["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"],
        )
