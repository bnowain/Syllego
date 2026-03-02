"""
conftest.py — Shared fixtures for all MMI test modules.
"""
from subprocess import CompletedProcess

import pytest

from mmi.engine.base import IngestionResult


@pytest.fixture
def tmp_output_dir(tmp_path):
    """A temporary output directory (created)."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def tmp_debug_dir(tmp_path):
    """A temporary debug directory for failure bundles (created)."""
    d = tmp_path / "debug"
    d.mkdir()
    return d


@pytest.fixture
def tmp_db_path(tmp_path):
    """A temporary path for the SQLite DB (file not pre-created)."""
    return tmp_path / "test_history.db"


@pytest.fixture
def make_completed_process():
    """Factory for subprocess.CompletedProcess instances."""
    def factory(args=None, returncode=0, stdout="", stderr=""):
        return CompletedProcess(
            args=args or ["cmd"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
    return factory


@pytest.fixture
def sample_result():
    """Factory for IngestionResult instances with sensible defaults."""
    def factory(**kwargs):
        defaults = dict(
            success=True,
            url="https://example.com/video",
            worker_name="TestWorker",
            filename="/tmp/video.mp4",
        )
        defaults.update(kwargs)
        return IngestionResult(**defaults)
    return factory
