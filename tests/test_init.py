"""
test_init.py — Tests for the mmi public API and lazy-singleton behaviour.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

import mmi
from mmi.engine.base import IngestionResult


def _success(**kw):
    d = dict(success=True, url="https://x.com", worker_name="W")
    d.update(kw)
    return IngestionResult(**d)


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

class TestPublicApi:
    def test_version_string(self):
        assert mmi.__version__ == "0.1.0"

    def test_all_contains_ingest(self):
        assert "ingest" in mmi.__all__

    def test_all_contains_ingest_m3u8(self):
        assert "ingest_m3u8" in mmi.__all__

    def test_all_contains_ingestion_result(self):
        assert "IngestionResult" in mmi.__all__

    def test_ingest_is_callable(self):
        assert callable(mmi.ingest)

    def test_ingest_m3u8_is_callable(self):
        assert callable(mmi.ingest_m3u8)

    def test_ingestion_result_importable_from_mmi(self):
        from mmi import IngestionResult
        assert IngestionResult is not None


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

class TestLazySingleton:
    def setup_method(self):
        # Reset the singleton before each test
        mmi._router = None

    def test_singleton_created_on_first_call(self):
        with patch("mmi.engine.router.Router.ingest", return_value=_success()):
            mmi.ingest("https://x.com")
        assert mmi._router is not None

    def test_singleton_reused_on_second_call(self):
        with patch("mmi.engine.router.Router.ingest", return_value=_success()):
            mmi.ingest("https://x.com")
            router1 = mmi._router
            mmi.ingest("https://x.com")
            router2 = mmi._router
        assert router1 is router2

    def test_recreates_when_output_dir_provided(self, tmp_path):
        with patch("mmi.engine.router.Router.ingest", return_value=_success()):
            mmi.ingest("https://x.com")
            router1 = mmi._router
            mmi.ingest("https://x.com", output_dir=tmp_path)
            router2 = mmi._router
        assert router1 is not router2

    def test_ingest_delegates_result(self):
        with patch("mmi.engine.router.Router.ingest", return_value=_success()):
            result = mmi.ingest("https://x.com")
        assert result.success is True

    def test_ingest_failure_propagated(self):
        fail = IngestionResult(success=False, url="https://x.com", worker_name="W", error_code="1", error_message="f")
        with patch("mmi.engine.router.Router.ingest", return_value=fail):
            result = mmi.ingest("https://x.com")
        assert result.success is False

    def test_ingest_m3u8_delegates_result(self):
        ok = _success(url="https://x.com/live.m3u8", worker_name="CustomWorker")
        with patch("mmi.engine.router.Router.ingest_m3u8", return_value=ok):
            result = mmi.ingest_m3u8("https://x.com/live.m3u8", "https://x.com")
        assert result.success is True

    def test_ingest_m3u8_passes_referer(self):
        ok = _success()
        with patch("mmi.engine.router.Router.ingest_m3u8", return_value=ok) as mock:
            mmi.ingest_m3u8("https://x.com/live.m3u8", "https://x.com/page")
            call_args = mock.call_args
        assert call_args[0][1] == "https://x.com/page"
