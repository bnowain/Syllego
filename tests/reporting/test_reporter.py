"""
reporting/test_reporter.py — Tests for write_failure_bundle.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mmi.engine.base import IngestionResult
from mmi.reporting.reporter import write_failure_bundle


def _result(**kwargs):
    defaults = dict(
        success=False,
        url="https://example.com/video",
        worker_name="TestWorker",
        error_code="404",
        error_message="Not found",
    )
    defaults.update(kwargs)
    return IngestionResult(**defaults)


class TestWriteFailureBundle:
    def test_creates_file(self, tmp_debug_dir):
        path = write_failure_bundle(_result(), debug_dir=tmp_debug_dir)
        assert path.exists()

    def test_filename_starts_with_failure_bundle(self, tmp_debug_dir):
        path = write_failure_bundle(_result(), debug_dir=tmp_debug_dir)
        assert path.name.startswith("failure_bundle_")

    def test_filename_has_json_suffix(self, tmp_debug_dir):
        path = write_failure_bundle(_result(), debug_dir=tmp_debug_dir)
        assert path.suffix == ".json"

    def test_json_has_expected_keys(self, tmp_debug_dir):
        path = write_failure_bundle(_result(), debug_dir=tmp_debug_dir)
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)
        expected = {"url", "worker", "error_code", "error_message", "stack_trace", "page_html", "timestamp", "metadata"}
        assert set(bundle.keys()) == expected

    def test_json_content_matches_result(self, tmp_debug_dir):
        r = _result(url="https://example.com", error_code="403", error_message="Forbidden")
        path = write_failure_bundle(r, debug_dir=tmp_debug_dir)
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)
        assert bundle["url"] == "https://example.com"
        assert bundle["error_code"] == "403"
        assert bundle["error_message"] == "Forbidden"

    def test_returns_path_object(self, tmp_debug_dir):
        path = write_failure_bundle(_result(), debug_dir=tmp_debug_dir)
        assert isinstance(path, Path)

    def test_creates_debug_dir_if_missing(self, tmp_path):
        new_dir = tmp_path / "nonexistent_debug"
        assert not new_dir.exists()
        write_failure_bundle(_result(), debug_dir=new_dir)
        assert new_dir.exists()

    def test_never_raises_on_io_error(self, tmp_debug_dir):
        # Even if open() throws, the function must not propagate
        r = _result()
        with patch("builtins.open", side_effect=PermissionError("no access")):
            path = write_failure_bundle(r, debug_dir=tmp_debug_dir)
        assert path is not None

    def test_utf8_content_preserved(self, tmp_debug_dir):
        r = _result(error_message="Ünïcödë — téxt with 中文")
        path = write_failure_bundle(r, debug_dir=tmp_debug_dir)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Ünïcödë" in content

    def test_none_fields_serialized_as_null(self, tmp_debug_dir):
        r = _result(stack_trace=None, page_html=None)
        path = write_failure_bundle(r, debug_dir=tmp_debug_dir)
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)
        assert bundle["stack_trace"] is None
        assert bundle["page_html"] is None

    def test_metadata_round_trips(self, tmp_debug_dir):
        r = _result()
        r.metadata["extra_key"] = "extra_value"
        path = write_failure_bundle(r, debug_dir=tmp_debug_dir)
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)
        assert bundle["metadata"]["extra_key"] == "extra_value"
