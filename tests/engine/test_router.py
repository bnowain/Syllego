"""
engine/test_router.py — Tests for Router dispatch, DB recording, and failure bundles.
"""
from unittest.mock import MagicMock, patch

import pytest

from mmi.engine.base import BaseWorker, IngestionResult
from mmi.engine.router import Router, _all_subclasses


def _success(url="https://x.com", worker_name="W", filename="f.mp4"):
    return IngestionResult(success=True, url=url, worker_name=worker_name, filename=filename)


def _fail(url="https://x.com", worker_name="W"):
    return IngestionResult(
        success=False, url=url, worker_name=worker_name,
        error_code="1", error_message="failed",
    )


def _mock_worker(priority=50, can_handle=True, result=None):
    """Create a MagicMock that behaves like a BaseWorker."""
    w = MagicMock(spec=BaseWorker)
    w.priority = priority
    w.can_handle.return_value = can_handle
    w.safe_download.return_value = result or _success()
    return w


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestRouterInit:
    def test_default_output_dir(self):
        from mmi.config import MMI_OUTPUT_DIR
        r = Router()
        assert r.output_dir == MMI_OUTPUT_DIR

    def test_custom_output_dir(self, tmp_path):
        r = Router(output_dir=tmp_path)
        assert r.output_dir == tmp_path


# ---------------------------------------------------------------------------
# Worker discovery
# ---------------------------------------------------------------------------

class TestWorkerDiscovery:
    def test_workers_sorted_by_priority(self, tmp_path):
        r = Router(output_dir=tmp_path)
        workers = r._get_workers()
        priorities = [w.priority for w in workers]
        assert priorities == sorted(priorities)

    def test_custom_worker_never_matches_any_url(self, tmp_path):
        # CustomWorker.can_handle() is always False, so even if it appears in the
        # worker list it is never dispatched. This is the behavioral guarantee.
        from mmi.engine.custom_worker import CustomWorker
        r = Router(output_dir=tmp_path)
        workers = r._get_workers()
        for w in workers:
            if isinstance(w, CustomWorker):
                assert not w.can_handle("https://anything.com")

    def test_generic_worker_is_included(self, tmp_path):
        from mmi.engine.generic_worker import GenericWorker
        r = Router(output_dir=tmp_path)
        workers = r._get_workers()
        assert any(isinstance(w, GenericWorker) for w in workers)


# ---------------------------------------------------------------------------
# ingest dispatch
# ---------------------------------------------------------------------------

class TestIngest:
    def test_dispatches_to_matching_worker(self, tmp_path):
        w = _mock_worker(result=_success())
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch.object(Router, "_get_workers", return_value=[w]):
            result = Router(output_dir=tmp_path).ingest("https://x.com")
        assert result.success is True

    def test_success_records_in_db(self, tmp_path):
        w = _mock_worker(result=_success())
        with patch("mmi.engine.router.db.record_download") as mock_db, \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch.object(Router, "_get_workers", return_value=[w]):
            Router(output_dir=tmp_path).ingest("https://x.com")
        assert mock_db.called
        assert mock_db.call_args[1]["download_status"] == "success"

    def test_success_does_not_write_bundle(self, tmp_path):
        w = _mock_worker(result=_success())
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle") as mock_bundle, \
             patch.object(Router, "_get_workers", return_value=[w]):
            Router(output_dir=tmp_path).ingest("https://x.com")
        mock_bundle.assert_not_called()

    def test_failure_writes_bundle(self, tmp_path):
        w = _mock_worker(result=_fail())
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle") as mock_bundle, \
             patch.object(Router, "_get_workers", return_value=[w]):
            result = Router(output_dir=tmp_path).ingest("https://x.com")
        assert result.success is False
        mock_bundle.assert_called_once()

    def test_failure_records_failed_status_in_db(self, tmp_path):
        w = _mock_worker(result=_fail())
        with patch("mmi.engine.router.db.record_download") as mock_db, \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch.object(Router, "_get_workers", return_value=[w]):
            Router(output_dir=tmp_path).ingest("https://x.com")
        assert mock_db.call_args[1]["download_status"] == "failed"

    def test_falls_through_to_second_worker_on_first_fail(self, tmp_path):
        w1 = _mock_worker(priority=10, result=_fail(worker_name="W1"))
        w2 = _mock_worker(priority=20, result=_success(worker_name="W2"))
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch.object(Router, "_get_workers", return_value=[w1, w2]):
            result = Router(output_dir=tmp_path).ingest("https://x.com")
        assert result.success is True
        assert result.worker_name == "W2"

    def test_skips_workers_that_cannot_handle(self, tmp_path):
        w_no = _mock_worker(can_handle=False, result=_success(worker_name="W_NO"))
        w_yes = _mock_worker(can_handle=True, result=_success(worker_name="W_YES"))
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch.object(Router, "_get_workers", return_value=[w_no, w_yes]):
            result = Router(output_dir=tmp_path).ingest("https://x.com")
        assert result.worker_name == "W_YES"
        w_no.safe_download.assert_not_called()

    def test_no_matching_worker_returns_no_worker_error(self, tmp_path):
        w = _mock_worker(can_handle=False)
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch.object(Router, "_get_workers", return_value=[w]):
            result = Router(output_dir=tmp_path).ingest("https://x.com")
        assert result.success is False
        assert result.error_code == "NO_WORKER"


# ---------------------------------------------------------------------------
# ingest_m3u8
# ---------------------------------------------------------------------------

class TestIngestM3u8:
    def test_delegates_to_custom_worker(self, tmp_path):
        success = _success(url="https://x.com/live.m3u8", worker_name="CustomWorker")
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch("mmi.engine.custom_worker.CustomWorker.safe_download_m3u8", return_value=success):
            result = Router(output_dir=tmp_path).ingest_m3u8(
                "https://x.com/live.m3u8", "https://x.com/page"
            )
        assert result.success is True
        assert result.worker_name == "CustomWorker"

    def test_records_m3u8_success_in_db(self, tmp_path):
        success = _success(url="https://x.com/live.m3u8", worker_name="CustomWorker")
        with patch("mmi.engine.router.db.record_download") as mock_db, \
             patch("mmi.engine.router.write_failure_bundle"), \
             patch("mmi.engine.custom_worker.CustomWorker.safe_download_m3u8", return_value=success):
            Router(output_dir=tmp_path).ingest_m3u8("https://x.com/live.m3u8", "https://x.com")
        assert mock_db.call_args[1]["download_status"] == "success"

    def test_m3u8_failure_writes_bundle(self, tmp_path):
        fail = _fail(url="https://x.com/live.m3u8", worker_name="CustomWorker")
        with patch("mmi.engine.router.db.record_download"), \
             patch("mmi.engine.router.write_failure_bundle") as mock_bundle, \
             patch("mmi.engine.custom_worker.CustomWorker.safe_download_m3u8", return_value=fail):
            Router(output_dir=tmp_path).ingest_m3u8("https://x.com/live.m3u8", "https://x.com")
        mock_bundle.assert_called_once()


# ---------------------------------------------------------------------------
# _all_subclasses helper
# ---------------------------------------------------------------------------

class TestAllSubclasses:
    def test_finds_concrete_subclasses(self):
        # Import workers to ensure they're registered
        import mmi.engine.rumble_worker  # noqa: F401
        import mmi.engine.generic_worker  # noqa: F401

        subs = _all_subclasses(BaseWorker)
        names = [cls.__name__ for cls in subs]
        assert "RumbleWorker" in names
        assert "GenericWorker" in names

    def test_excludes_abstract_base(self):
        subs = _all_subclasses(BaseWorker)
        assert BaseWorker not in subs
