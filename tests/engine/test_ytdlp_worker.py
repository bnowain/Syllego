"""
engine/test_ytdlp_worker.py — Tests for YtdlpWorker.
"""
from unittest.mock import patch

import pytest

from mmi.engine.base import IngestionResult
from mmi.engine.ytdlp_worker import YtdlpWorker

_YTDLP_HOSTS = [
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "tiktok.com",
    "dailymotion.com",
]


class TestYtdlpWorker:
    def setup_method(self):
        self.worker = YtdlpWorker()

    def test_priority(self):
        assert self.worker.priority == 40

    @pytest.mark.parametrize("host", _YTDLP_HOSTS)
    def test_can_handle_known_hosts(self, host):
        assert self.worker.can_handle(f"https://{host}/video/123")

    def test_cannot_handle_unknown_site(self):
        assert not self.worker.can_handle("https://unknownsite.example.com/video")

    def test_download_success(self, tmp_path):
        mock_result = IngestionResult(
            success=True, url="https://youtube.com/v",
            worker_name="YtdlpWorker", filename="/tmp/v.mp4",
        )
        with patch("mmi.engine.ytdlp_worker.run_ytdlp", return_value=mock_result):
            r = self.worker.download("https://youtube.com/watch?v=abc", tmp_path)
        assert r.success is True

    def test_download_failure(self, tmp_path):
        mock_result = IngestionResult(
            success=False, url="https://youtube.com/v",
            worker_name="YtdlpWorker", error_code="403",
        )
        with patch("mmi.engine.ytdlp_worker.run_ytdlp", return_value=mock_result):
            r = self.worker.download("https://youtube.com/watch?v=abc", tmp_path)
        assert r.success is False

    def test_passes_format_selection_args(self, tmp_path):
        with patch("mmi.engine.ytdlp_worker.run_ytdlp") as mock:
            mock.return_value = IngestionResult(success=True, url="u", worker_name="w")
            self.worker.download("https://youtube.com/watch?v=abc", tmp_path)
            kwargs = mock.call_args[1]
        extra = kwargs.get("extra_args", [])
        assert "-f" in extra
