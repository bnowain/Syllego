"""
test_cli.py — Tests for the MMI command-line interface.
"""
import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mmi.cli import _print_result, _show_history, build_parser, main
from mmi.engine.base import IngestionResult


def _success(**kw):
    defaults = dict(success=True, url="https://x.com", worker_name="W", filename="/tmp/v.mp4")
    defaults.update(kw)
    return IngestionResult(**defaults)


def _fail(**kw):
    defaults = dict(success=False, url="https://x.com", worker_name="W", error_message="failed")
    defaults.update(kw)
    return IngestionResult(**defaults)


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_returns_argument_parser(self):
        assert isinstance(build_parser(), argparse.ArgumentParser)

    def test_url_is_optional(self):
        args = build_parser().parse_args([])
        assert args.url is None

    def test_url_positional(self):
        args = build_parser().parse_args(["https://x.com"])
        assert args.url == "https://x.com"

    def test_m3u8_flag(self):
        args = build_parser().parse_args(["--m3u8", "https://s.m3u8", "--referer", "https://x.com"])
        assert args.m3u8 == "https://s.m3u8"
        assert args.referer == "https://x.com"

    def test_history_flag(self):
        args = build_parser().parse_args(["--history"])
        assert args.history is True

    def test_output_flag_short(self):
        args = build_parser().parse_args(["-o", "/tmp/out"])
        assert args.output == "/tmp/out"

    def test_output_flag_long(self):
        args = build_parser().parse_args(["--output", "/tmp/out"])
        assert args.output == "/tmp/out"

    def test_verbose_flag_short(self):
        args = build_parser().parse_args(["-v"])
        assert args.verbose is True

    def test_version_flag_exits(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--version"])


# ---------------------------------------------------------------------------
# main() paths
# ---------------------------------------------------------------------------

class TestMain:
    def test_history_path_calls_show_history(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mmi", "--history"])
        with patch("mmi.cli._show_history") as mock_hist:
            main()
            mock_hist.assert_called_once()

    def test_m3u8_path_success_exits_0(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mmi", "--m3u8", "https://s.m3u8", "--referer", "https://x.com"])
        with patch("mmi.engine.router.Router.ingest_m3u8", return_value=_success()):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0

    def test_m3u8_missing_referer_exits_nonzero(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mmi", "--m3u8", "https://s.m3u8"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code != 0

    def test_auto_route_success_exits_0(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mmi", "https://x.com"])
        with patch("mmi.engine.router.Router.ingest", return_value=_success()):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0

    def test_auto_route_failure_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mmi", "https://x.com"])
        with patch("mmi.engine.router.Router.ingest", return_value=_fail()):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_no_url_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mmi"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_output_override_accepted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["mmi", "-o", str(tmp_path), "https://x.com"])
        with patch("mmi.engine.router.Router.ingest", return_value=_success()):
            with pytest.raises(SystemExit):
                main()


# ---------------------------------------------------------------------------
# _show_history
# ---------------------------------------------------------------------------

class TestShowHistory:
    def test_empty_table_prints_message(self, capsys):
        with patch("mmi.db.history.get_recent", return_value=[]):
            _show_history()
        out = capsys.readouterr().out
        assert "No downloads recorded" in out

    def test_with_records_prints_url(self, capsys):
        rows = [{
            "id": 1,
            "download_status": "success",
            "worker_name": "RumbleWorker",
            "timestamp": "2024-01-01T12:00:00",
            "url": "https://rumble.com/v1",
            "filename": None,
            "error_message": None,
        }]
        with patch("mmi.db.history.get_recent", return_value=rows):
            _show_history()
        out = capsys.readouterr().out
        assert "rumble.com" in out or "success" in out


# ---------------------------------------------------------------------------
# _print_result
# ---------------------------------------------------------------------------

class TestPrintResult:
    def test_success_prints_ok(self, capsys):
        _print_result(_success(worker_name="RumbleWorker"))
        out = capsys.readouterr().out
        assert "OK" in out

    def test_failure_prints_fail_to_stderr(self, capsys):
        _print_result(_fail())
        err = capsys.readouterr().err
        assert "FAIL" in err

    def test_verbose_shows_stack_trace(self, capsys):
        r = _fail(stack_trace="Traceback (most recent call last):")
        _print_result(r, verbose=True)
        err = capsys.readouterr().err
        assert "Traceback" in err

    def test_non_verbose_hides_stack_trace(self, capsys):
        r = _fail(stack_trace="Traceback (most recent call last):")
        _print_result(r, verbose=False)
        err = capsys.readouterr().err
        assert "Traceback" not in err
