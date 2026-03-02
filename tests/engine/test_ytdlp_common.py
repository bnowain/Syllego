"""
engine/test_ytdlp_common.py — Tests for the shared yt-dlp subprocess helper.

All subprocess.run calls are mocked — no real binaries invoked.
"""
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from mmi.engine._ytdlp_common import _extract_http_code, _parse_filename, run_ytdlp


def _proc(returncode=0, stdout="", stderr=""):
    return CompletedProcess(
        args=["yt-dlp"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# _parse_filename
# ---------------------------------------------------------------------------

class TestParseFilename:
    def test_last_line_extraction(self):
        stdout = "some info\n/path/to/video.mp4"
        assert _parse_filename(stdout) == "/path/to/video.mp4"

    def test_bracket_line_is_skipped_as_last_line(self):
        # If last line starts with '[', falls through to fallback scan
        # Destination line should be picked up by fallback
        stdout = "Destination: /path/to/video.mp4\n[youtube] Processing"
        # Fallback _DEST_RE should find the destination
        result = _parse_filename(stdout)
        assert result == "/path/to/video.mp4"

    def test_merger_regex_fallback(self):
        stdout = '[Merger] Merging formats into "video.mp4"'
        assert _parse_filename(stdout) == "video.mp4"

    def test_destination_regex_fallback(self):
        # When the Destination line is NOT the last line (last starts with '['),
        # the fallback regex scan picks up the path from the Destination line.
        stdout = "Destination: /path/to/video.mp4\n[youtube] Finished"
        assert _parse_filename(stdout) == "/path/to/video.mp4"

    def test_already_downloaded_regex_fallback(self):
        stdout = "[download] /path/to/video.mp4 has already been downloaded"
        assert _parse_filename(stdout) == "/path/to/video.mp4"

    def test_empty_string_returns_none(self):
        assert _parse_filename("") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_filename("   \n   \t  ") is None

    def test_error_line_not_returned_as_filename(self):
        # If the last non-empty line starts with ERROR, it should not be returned
        stdout = "some info\nERROR: something went wrong"
        result = _parse_filename(stdout)
        # Should be None (no fallback matches) or at least not the ERROR line
        assert result is None or not result.startswith("ERROR")

    def test_plain_path_as_only_line(self):
        assert _parse_filename("/downloads/video.mp4") == "/downloads/video.mp4"

    def test_multiple_lines_picks_last_non_bracket(self):
        stdout = "[info] Downloading\n/downloads/video.mp4\n"
        assert _parse_filename(stdout) == "/downloads/video.mp4"


# ---------------------------------------------------------------------------
# _extract_http_code
# ---------------------------------------------------------------------------

class TestExtractHttpCode:
    def test_extracts_403(self):
        assert _extract_http_code("ERROR: HTTP Error 403: Forbidden") == "403"

    def test_extracts_404(self):
        assert _extract_http_code("ERROR: HTTP Error 404: Not Found") == "404"

    def test_no_match_returns_none(self):
        assert _extract_http_code("Some other error") is None

    def test_case_insensitive(self):
        assert _extract_http_code("error: http error 403: forbidden") == "403"


# ---------------------------------------------------------------------------
# run_ytdlp
# ---------------------------------------------------------------------------

class TestRunYtdlp:
    def test_success_returns_true(self, tmp_path):
        with patch("mmi.engine._ytdlp_common.subprocess.run", return_value=_proc(stdout="/tmp/video.mp4")):
            result = run_ytdlp("https://x.com", tmp_path, "TestWorker")
        assert result.success is True

    def test_success_sets_filename(self, tmp_path):
        with patch("mmi.engine._ytdlp_common.subprocess.run", return_value=_proc(stdout="/tmp/video.mp4")):
            result = run_ytdlp("https://x.com", tmp_path, "TestWorker")
        assert result.filename == "/tmp/video.mp4"

    def test_nonzero_exit_with_http_code(self, tmp_path):
        with patch(
            "mmi.engine._ytdlp_common.subprocess.run",
            return_value=_proc(returncode=1, stderr="ERROR: HTTP Error 403: Forbidden"),
        ):
            result = run_ytdlp("https://x.com", tmp_path, "TestWorker")
        assert result.success is False
        assert result.error_code == "403"

    def test_nonzero_exit_without_http_code_uses_returncode(self, tmp_path):
        with patch(
            "mmi.engine._ytdlp_common.subprocess.run",
            return_value=_proc(returncode=1, stderr="generic error"),
        ):
            result = run_ytdlp("https://x.com", tmp_path, "TestWorker")
        assert result.success is False
        assert result.error_code == "1"

    def test_file_not_found_returns_error(self, tmp_path):
        with patch("mmi.engine._ytdlp_common.subprocess.run", side_effect=FileNotFoundError()):
            result = run_ytdlp("https://x.com", tmp_path, "TestWorker")
        assert result.success is False
        assert result.error_code == "YTDLP_NOT_FOUND"

    def test_generic_exception_returns_error(self, tmp_path):
        with patch("mmi.engine._ytdlp_common.subprocess.run", side_effect=OSError("os error")):
            result = run_ytdlp("https://x.com", tmp_path, "TestWorker")
        assert result.success is False
        assert result.error_code == "SUBPROCESS_ERROR"

    def test_creates_output_dir(self, tmp_path):
        new_dir = tmp_path / "new_subdir"
        assert not new_dir.exists()
        with patch("mmi.engine._ytdlp_common.subprocess.run", return_value=_proc(stdout="/tmp/v.mp4")):
            run_ytdlp("https://x.com", new_dir, "TestWorker")
        assert new_dir.exists()

    def test_extra_args_inserted_before_url(self, tmp_path):
        with patch("mmi.engine._ytdlp_common.subprocess.run") as mock_run:
            mock_run.return_value = _proc(stdout="/tmp/v.mp4")
            run_ytdlp(
                "https://x.com", tmp_path, "TestWorker",
                extra_args=["--cookies-from-browser", "chrome"],
            )
            cmd = mock_run.call_args[0][0]
        # URL must be last
        assert cmd[-1] == "https://x.com"
        # Extra args must appear in the command
        assert "--cookies-from-browser" in cmd
        assert "chrome" in cmd

    def test_no_extra_args_url_not_duplicated(self, tmp_path):
        with patch("mmi.engine._ytdlp_common.subprocess.run") as mock_run:
            mock_run.return_value = _proc(stdout="/tmp/v.mp4")
            run_ytdlp("https://x.com", tmp_path, "TestWorker", extra_args=None)
            cmd = mock_run.call_args[0][0]
        assert cmd.count("https://x.com") == 1
