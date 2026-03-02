"""
engine/test_custom_worker.py — Tests for CustomWorker, _url_to_slug, _unique_path.
"""
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from mmi.engine.custom_worker import CustomWorker, _unique_path, _url_to_slug


def _proc(returncode=0, stdout="", stderr=""):
    return CompletedProcess(args=["ffmpeg"], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------

class TestCanHandle:
    def test_always_false_for_any_url(self):
        w = CustomWorker()
        assert w.can_handle("https://anything.com/video") is False

    def test_always_false_for_empty_string(self):
        assert CustomWorker().can_handle("") is False

    def test_always_false_for_rumble(self):
        assert CustomWorker().can_handle("https://rumble.com/v1") is False


# ---------------------------------------------------------------------------
# download() — should raise NotImplementedError
# ---------------------------------------------------------------------------

class TestDownload:
    def test_raises_not_implemented(self, tmp_path):
        w = CustomWorker()
        with pytest.raises(NotImplementedError):
            w.download("https://example.com", tmp_path)

    def test_safe_download_catches_not_implemented(self, tmp_path):
        # BaseWorker.safe_download wraps download() — should not propagate
        w = CustomWorker()
        r = w.safe_download("https://example.com", tmp_path)
        assert r.success is False


# ---------------------------------------------------------------------------
# safe_download_m3u8
# ---------------------------------------------------------------------------

class TestSafeDownloadM3u8:
    def test_success(self, tmp_path):
        with patch("mmi.engine.custom_worker.subprocess.run", return_value=_proc(returncode=0)):
            r = CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/page",
                tmp_path,
            )
        assert r.success is True
        assert r.filename is not None

    def test_filename_ends_with_mp4(self, tmp_path):
        with patch("mmi.engine.custom_worker.subprocess.run", return_value=_proc(returncode=0)):
            r = CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/my-page",
                tmp_path,
            )
        assert r.filename.endswith(".mp4")

    def test_failure_nonzero_exit(self, tmp_path):
        with patch(
            "mmi.engine.custom_worker.subprocess.run",
            return_value=_proc(returncode=1, stderr="ffmpeg error"),
        ):
            r = CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/page",
                tmp_path,
            )
        assert r.success is False
        assert r.error_code == "1"

    def test_ffmpeg_not_found(self, tmp_path):
        with patch("mmi.engine.custom_worker.subprocess.run", side_effect=FileNotFoundError()):
            r = CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/page",
                tmp_path,
            )
        assert r.success is False
        assert r.error_code == "FFMPEG_NOT_FOUND"

    def test_generic_subprocess_exception(self, tmp_path):
        with patch("mmi.engine.custom_worker.subprocess.run", side_effect=OSError("os error")):
            r = CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/page",
                tmp_path,
            )
        assert r.success is False
        assert r.error_code == "SUBPROCESS_ERROR"

    def test_creates_output_dir(self, tmp_path):
        new_dir = tmp_path / "m3u8_out"
        assert not new_dir.exists()
        with patch("mmi.engine.custom_worker.subprocess.run", return_value=_proc()):
            CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/page",
                new_dir,
            )
        assert new_dir.exists()

    def test_command_calls_ffmpeg(self, tmp_path):
        with patch("mmi.engine.custom_worker.subprocess.run") as mock:
            mock.return_value = _proc()
            CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/page",
                tmp_path,
            )
            cmd = mock.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "https://stream.example.com/live.m3u8" in cmd

    def test_command_includes_stream_copy(self, tmp_path):
        with patch("mmi.engine.custom_worker.subprocess.run") as mock:
            mock.return_value = _proc()
            CustomWorker().safe_download_m3u8(
                "https://stream.example.com/live.m3u8",
                "https://example.com/page",
                tmp_path,
            )
            cmd = mock.call_args[0][0]
        assert "-c" in cmd
        assert "copy" in cmd


# ---------------------------------------------------------------------------
# _url_to_slug
# ---------------------------------------------------------------------------

class TestUrlToSlug:
    def test_extracts_last_path_segment(self):
        slug = _url_to_slug("https://example.com/some/video-page")
        assert slug == "video-page"

    def test_netloc_fallback_for_trailing_slash(self):
        slug = _url_to_slug("https://example.com/")
        assert "example" in slug

    def test_respects_max_len(self):
        slug = _url_to_slug("https://example.com/" + "a" * 100, max_len=20)
        assert len(slug) <= 20

    def test_special_chars_replaced_with_underscore(self):
        # Dot in filename is replaced since it's not \w or \-
        slug = _url_to_slug("https://example.com/video.mp4")
        assert "." not in slug

    def test_hyphen_preserved(self):
        slug = _url_to_slug("https://example.com/my-video")
        assert "-" in slug

    def test_empty_url_returns_string(self):
        result = _url_to_slug("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _unique_path
# ---------------------------------------------------------------------------

class TestUniquePath:
    def test_no_conflict_returns_original(self, tmp_path):
        p = tmp_path / "video.mp4"
        assert _unique_path(p) == p

    def test_one_conflict_appends_counter(self, tmp_path):
        p = tmp_path / "video.mp4"
        p.touch()
        result = _unique_path(p)
        assert result == tmp_path / "video_1.mp4"

    def test_multiple_conflicts_increments_counter(self, tmp_path):
        p = tmp_path / "video.mp4"
        p.touch()
        (tmp_path / "video_1.mp4").touch()
        result = _unique_path(p)
        assert result == tmp_path / "video_2.mp4"

    def test_preserves_file_suffix(self, tmp_path):
        p = tmp_path / "video.mkv"
        p.touch()
        result = _unique_path(p)
        assert result.suffix == ".mkv"
