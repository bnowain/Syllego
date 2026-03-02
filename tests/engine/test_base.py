"""
engine/test_base.py — Tests for IngestionResult dataclass and BaseWorker ABC.
"""
from pathlib import Path

import pytest

from mmi.engine.base import BaseWorker, IngestionResult


# ---------------------------------------------------------------------------
# Concrete workers used only in this test module
# ---------------------------------------------------------------------------

class _SucceedingWorker(BaseWorker):
    priority = 50

    def can_handle(self, url: str) -> bool:
        return True

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        return IngestionResult(success=True, url=url, worker_name="_SucceedingWorker")


class _RaisingWorker(BaseWorker):
    priority = 50

    def can_handle(self, url: str) -> bool:
        return True

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        raise RuntimeError("unexpected boom")


# ---------------------------------------------------------------------------
# IngestionResult
# ---------------------------------------------------------------------------

class TestIngestionResult:
    def test_required_fields(self):
        r = IngestionResult(success=True, url="https://x.com", worker_name="W")
        assert r.success is True
        assert r.url == "https://x.com"
        assert r.worker_name == "W"

    def test_optional_fields_default_to_none(self):
        r = IngestionResult(success=True, url="u", worker_name="w")
        assert r.filename is None
        assert r.error_code is None
        assert r.error_message is None
        assert r.stack_trace is None
        assert r.page_html is None

    def test_metadata_defaults_to_empty_dict(self):
        r = IngestionResult(success=True, url="u", worker_name="w")
        assert r.metadata == {}

    def test_all_fields_roundtrip(self):
        r = IngestionResult(
            success=False,
            url="https://x.com",
            worker_name="W",
            filename="file.mp4",
            error_code="404",
            error_message="Not found",
            stack_trace="Traceback ...",
            page_html="<html>",
            metadata={"key": "val"},
        )
        assert r.success is False
        assert r.error_code == "404"
        assert r.metadata == {"key": "val"}

    def test_metadata_independence(self):
        # Each instance gets its own metadata dict (default_factory)
        r1 = IngestionResult(success=True, url="u", worker_name="w")
        r2 = IngestionResult(success=True, url="u", worker_name="w")
        r1.metadata["x"] = 1
        assert "x" not in r2.metadata


# ---------------------------------------------------------------------------
# BaseWorker ABC
# ---------------------------------------------------------------------------

class TestBaseWorkerAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseWorker()  # type: ignore[abstract]

    def test_subclass_without_can_handle_raises(self):
        class Partial(BaseWorker):
            priority = 99

            def download(self, url, output_dir):
                pass

        with pytest.raises(TypeError):
            Partial()

    def test_subclass_without_download_raises(self):
        class Partial(BaseWorker):
            priority = 99

            def can_handle(self, url):
                return True

        with pytest.raises(TypeError):
            Partial()


# ---------------------------------------------------------------------------
# safe_download
# ---------------------------------------------------------------------------

class TestSafeDownload:
    def test_delegates_on_success(self, tmp_path):
        w = _SucceedingWorker()
        r = w.safe_download("https://x.com", tmp_path)
        assert r.success is True

    def test_catches_unexpected_exception(self, tmp_path):
        w = _RaisingWorker()
        r = w.safe_download("https://x.com", tmp_path)
        assert r.success is False

    def test_error_code_on_exception(self, tmp_path):
        w = _RaisingWorker()
        r = w.safe_download("https://x.com", tmp_path)
        assert r.error_code == "UNEXPECTED_EXCEPTION"

    def test_error_message_contains_exception_text(self, tmp_path):
        w = _RaisingWorker()
        r = w.safe_download("https://x.com", tmp_path)
        assert "unexpected boom" in r.error_message

    def test_preserves_url(self, tmp_path):
        w = _RaisingWorker()
        r = w.safe_download("https://x.com", tmp_path)
        assert r.url == "https://x.com"

    def test_preserves_worker_name(self, tmp_path):
        w = _RaisingWorker()
        r = w.safe_download("https://x.com", tmp_path)
        assert r.worker_name == "_RaisingWorker"


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_format(self):
        w = _SucceedingWorker()
        assert repr(w) == "<_SucceedingWorker priority=50>"
