"""
engine/test_odysee_worker.py — Tests for OdyseeWorker.
"""
from unittest.mock import patch

import pytest

from mmi.engine.base import IngestionResult
from mmi.engine.odysee_worker import OdyseeWorker


class TestOdyseeWorker:
    def setup_method(self):
        self.worker = OdyseeWorker()

    def test_priority(self):
        assert self.worker.priority == 20

    def test_can_handle_odysee(self):
        assert self.worker.can_handle("https://odysee.com/@channel/video")

    def test_cannot_handle_youtube(self):
        assert not self.worker.can_handle("https://youtube.com/watch?v=abc")

    def test_cannot_handle_rumble(self):
        assert not self.worker.can_handle("https://rumble.com/v1")

    def test_download_success(self, tmp_path):
        mock_result = IngestionResult(
            success=True, url="https://odysee.com/v",
            worker_name="OdyseeWorker", filename="/tmp/v.mp4",
        )
        with patch("mmi.engine.odysee_worker.run_ytdlp", return_value=mock_result):
            r = self.worker.download("https://odysee.com/v", tmp_path)
        assert r.success is True

    def test_download_failure(self, tmp_path):
        mock_result = IngestionResult(
            success=False, url="https://odysee.com/v",
            worker_name="OdyseeWorker", error_code="403",
        )
        with patch("mmi.engine.odysee_worker.run_ytdlp", return_value=mock_result):
            r = self.worker.download("https://odysee.com/v", tmp_path)
        assert r.success is False

    def test_passes_extractor_retries_arg(self, tmp_path):
        with patch("mmi.engine.odysee_worker.run_ytdlp") as mock:
            mock.return_value = IngestionResult(success=True, url="u", worker_name="w")
            self.worker.download("https://odysee.com/v", tmp_path)
            kwargs = mock.call_args[1]
        assert "--extractor-retries" in kwargs.get("extra_args", [])
