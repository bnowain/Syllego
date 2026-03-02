"""
engine/test_gallery_worker.py — Tests for GalleryWorker.
"""
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from mmi.engine.base import IngestionResult
from mmi.engine.gallery_worker import GalleryWorker

_GALLERY_HOSTS = [
    "instagram.com",
    "reddit.com",
    "imgur.com",
    "deviantart.com",
    "flickr.com",
]


def _proc(returncode=0, stdout="", stderr=""):
    return CompletedProcess(args=["gallery-dl"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestGalleryWorker:
    def setup_method(self):
        self.worker = GalleryWorker()

    def test_priority(self):
        assert self.worker.priority == 30

    @pytest.mark.parametrize("host", _GALLERY_HOSTS)
    def test_can_handle_gallery_hosts(self, host):
        assert self.worker.can_handle(f"https://{host}/post/123")

    def test_cannot_handle_youtube(self):
        assert not self.worker.can_handle("https://youtube.com/watch?v=abc")

    def test_download_success(self, tmp_path):
        with patch("mmi.engine.gallery_worker.subprocess.run", return_value=_proc(stdout="/tmp/img.jpg")):
            r = self.worker.download("https://instagram.com/p/abc", tmp_path)
        assert r.success is True
        assert r.filename == "/tmp/img.jpg"

    def test_download_failure_nonzero_exit(self, tmp_path):
        with patch("mmi.engine.gallery_worker.subprocess.run", return_value=_proc(returncode=1, stderr="error")):
            r = self.worker.download("https://instagram.com/p/abc", tmp_path)
        assert r.success is False

    def test_gallery_dl_not_found(self, tmp_path):
        with patch("mmi.engine.gallery_worker.subprocess.run", side_effect=FileNotFoundError()):
            r = self.worker.download("https://instagram.com/p/abc", tmp_path)
        assert r.success is False
        assert r.error_code == "GALLERY_DL_NOT_FOUND"

    def test_generic_subprocess_exception(self, tmp_path):
        with patch("mmi.engine.gallery_worker.subprocess.run", side_effect=OSError("oops")):
            r = self.worker.download("https://instagram.com/p/abc", tmp_path)
        assert r.success is False
        assert r.error_code == "SUBPROCESS_ERROR"

    def test_files_downloaded_metadata(self, tmp_path):
        stdout = "/tmp/img1.jpg\n/tmp/img2.jpg\n/tmp/img3.jpg"
        with patch("mmi.engine.gallery_worker.subprocess.run", return_value=_proc(stdout=stdout)):
            r = self.worker.download("https://instagram.com/p/abc", tmp_path)
        assert r.metadata["files_downloaded"] == 3

    def test_creates_output_dir(self, tmp_path):
        new_dir = tmp_path / "gallery_out"
        assert not new_dir.exists()
        with patch("mmi.engine.gallery_worker.subprocess.run", return_value=_proc()):
            self.worker.download("https://instagram.com/p/abc", new_dir)
        assert new_dir.exists()

    def test_empty_stdout_gives_none_filename(self, tmp_path):
        with patch("mmi.engine.gallery_worker.subprocess.run", return_value=_proc(stdout="")):
            r = self.worker.download("https://instagram.com/p/abc", tmp_path)
        assert r.success is True
        assert r.filename is None
