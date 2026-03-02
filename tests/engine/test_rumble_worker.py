"""
engine/test_rumble_worker.py — Tests for RumbleWorker.
"""
from unittest.mock import patch

import pytest

from mmi.engine.base import IngestionResult
from mmi.engine.rumble_worker import RumbleWorker


class TestRumbleWorker:
    def setup_method(self):
        self.worker = RumbleWorker()

    def test_priority(self):
        assert self.worker.priority == 10

    def test_can_handle_rumble_com(self):
        assert self.worker.can_handle("https://rumble.com/v123-test.html")

    def test_can_handle_rmbl_ws(self):
        assert self.worker.can_handle("https://rmbl.ws/abc")

    def test_cannot_handle_youtube(self):
        assert not self.worker.can_handle("https://youtube.com/watch?v=abc")

    def test_cannot_handle_unrelated_site(self):
        assert not self.worker.can_handle("https://vimeo.com/123")

    def test_download_success(self, tmp_path):
        mock_result = IngestionResult(
            success=True, url="https://rumble.com/v1",
            worker_name="RumbleWorker", filename="/tmp/v.mp4",
        )
        with patch("mmi.engine.rumble_worker.run_ytdlp", return_value=mock_result):
            r = self.worker.download("https://rumble.com/v1", tmp_path)
        assert r.success is True

    def test_download_failure(self, tmp_path):
        mock_result = IngestionResult(
            success=False, url="https://rumble.com/v1",
            worker_name="RumbleWorker", error_code="403",
        )
        with patch("mmi.engine.rumble_worker.run_ytdlp", return_value=mock_result):
            r = self.worker.download("https://rumble.com/v1", tmp_path)
        assert r.success is False

    def test_passes_no_extra_args(self, tmp_path):
        with patch("mmi.engine.rumble_worker.run_ytdlp") as mock:
            mock.return_value = IngestionResult(success=True, url="u", worker_name="w")
            self.worker.download("https://rumble.com/v1", tmp_path)
            kwargs = mock.call_args[1]
        assert kwargs.get("extra_args") is None
