"""
odysee_worker.py — Worker for Odysee/LBRY video downloads (priority 20).

Handles: odysee.com
Strategy: yt-dlp (has native Odysee support).

AI-MAINTENANCE NOTE:
  Odysee occasionally changes their CDN endpoints. If downloads fail with 403,
  try adding '--extractor-retries 3' to extra_args. Also check if the lbry://
  protocol URL form works better than the https://odysee.com form.
"""
from __future__ import annotations

from pathlib import Path

from mmi.engine._ytdlp_common import run_ytdlp
from mmi.engine.base import BaseWorker, IngestionResult

_ODYSEE_HOSTS = ("odysee.com",)


class OdyseeWorker(BaseWorker):
    priority = 20

    def can_handle(self, url: str) -> bool:
        return any(host in url for host in _ODYSEE_HOSTS)

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        return run_ytdlp(
            url=url,
            output_dir=output_dir,
            worker_name=type(self).__name__,
            extra_args=["--extractor-retries", "3"],
        )
