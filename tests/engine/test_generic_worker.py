"""
engine/test_generic_worker.py — Tests for GenericWorker (catch-all + httpx fallback).
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from mmi.engine.base import IngestionResult
from mmi.engine.generic_worker import GenericWorker


def _fail(url="https://x.com/file.mp4"):
    return IngestionResult(
        success=False, url=url, worker_name="GenericWorker",
        error_code="1", error_message="ytdlp fail",
    )


def _success(url="https://x.com/file.mp4", filename="/tmp/v.mp4"):
    return IngestionResult(
        success=True, url=url, worker_name="GenericWorker", filename=filename,
    )


def _mock_httpx_stream(iter_bytes_data=None):
    """Build a mock for httpx.stream that works as a context manager."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_bytes.return_value = iter(iter_bytes_data or [b"data"])

    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_resp)
    mock_cm.__exit__ = MagicMock(return_value=False)
    return mock_cm


class TestGenericWorker:
    def setup_method(self):
        self.worker = GenericWorker()

    def test_priority_is_100(self):
        assert self.worker.priority == 100

    def test_can_handle_always_true(self):
        assert self.worker.can_handle("https://anything.com") is True

    def test_can_handle_unknown_site(self):
        assert self.worker.can_handle("https://unknown-site.example.org/path") is True

    def test_can_handle_empty_string(self):
        assert self.worker.can_handle("") is True

    def test_ytdlp_success_short_circuits(self, tmp_path):
        with patch("mmi.engine.generic_worker.run_ytdlp", return_value=_success()):
            r = self.worker.download("https://x.com/file.mp4", tmp_path)
        assert r.success is True
        assert r.filename == "/tmp/v.mp4"

    def test_ytdlp_fail_then_httpx_success(self, tmp_path):
        import httpx as real_httpx

        with patch("mmi.engine.generic_worker.run_ytdlp", return_value=_fail()):
            with patch.object(real_httpx, "stream", return_value=_mock_httpx_stream()):
                r = self.worker.download("https://x.com/file.mp4", tmp_path)
        assert r.success is True

    def test_both_ytdlp_and_httpx_fail(self, tmp_path):
        import httpx as real_httpx

        with patch("mmi.engine.generic_worker.run_ytdlp", return_value=_fail()):
            with patch.object(real_httpx, "stream", side_effect=Exception("network error")):
                r = self.worker.download("https://x.com/file.mp4", tmp_path)
        assert r.success is False
        assert r.error_code == "DIRECT_DOWNLOAD_FAILED"

    def test_httpx_not_installed(self, tmp_path):
        with patch("mmi.engine.generic_worker.run_ytdlp", return_value=_fail()):
            with patch.dict(sys.modules, {"httpx": None}):
                r = self.worker._direct_download("https://x.com/file.mp4", tmp_path)
        assert r.success is False
        assert r.error_code == "HTTPX_NOT_FOUND"

    def test_filename_derived_from_url(self, tmp_path):
        import httpx as real_httpx

        with patch("mmi.engine.generic_worker.run_ytdlp", return_value=_fail()):
            with patch.object(real_httpx, "stream", return_value=_mock_httpx_stream()):
                r = self.worker.download("https://x.com/myvideo.mp4", tmp_path)
        assert r.success is True
        assert "myvideo.mp4" in r.filename

    def test_no_extension_adds_bin(self, tmp_path):
        import httpx as real_httpx

        with patch("mmi.engine.generic_worker.run_ytdlp", return_value=_fail()):
            with patch.object(real_httpx, "stream", return_value=_mock_httpx_stream()):
                r = self.worker.download("https://x.com/path/noext", tmp_path)
        assert r.success is True
        assert r.filename.endswith(".bin")

    def test_empty_path_uses_download_bin(self, tmp_path):
        import httpx as real_httpx

        with patch("mmi.engine.generic_worker.run_ytdlp", return_value=_fail()):
            with patch.object(real_httpx, "stream", return_value=_mock_httpx_stream()):
                r = self.worker.download("https://x.com", tmp_path)
        assert r.success is True
        assert r.filename is not None

    def test_passes_no_check_certificate_to_ytdlp(self, tmp_path):
        with patch("mmi.engine.generic_worker.run_ytdlp") as mock:
            mock.return_value = _success()
            self.worker.download("https://x.com/file.mp4", tmp_path)
            kwargs = mock.call_args[1]
        assert "--no-check-certificate" in kwargs.get("extra_args", [])
