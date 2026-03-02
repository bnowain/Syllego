"""
_ytdlp_common.py — Shared yt-dlp subprocess helper.

Used by: RumbleWorker, OdyseeWorker, YtdlpWorker, GenericWorker.
Centralises the subprocess call, output parsing, and error handling so each
worker only needs to specify extra yt-dlp flags.

AI-MAINTENANCE NOTE:
  If yt-dlp changes its output format, fix `_parse_filename()` here — all workers
  will benefit automatically.
"""
from __future__ import annotations

import re
import subprocess
import sys
import traceback
from pathlib import Path

from mmi.config import CHROME_USER_AGENT, get_logger
from mmi.engine.base import IngestionResult

logger = get_logger("mmi.ytdlp")

# Matches "Destination: /path/to/file.ext" in yt-dlp stdout
_DEST_RE = re.compile(r"Destination:\s+(.+)", re.IGNORECASE)
# Matches "[Merger] Merging formats into "file.ext"" or "[download] /path/to/file.ext"
_MERGER_RE = re.compile(r'\[Merger\] Merging formats into "(.+)"', re.IGNORECASE)
_ALREADY_RE = re.compile(r"\[download\] (.+) has already been downloaded", re.IGNORECASE)


def run_ytdlp(
    url: str,
    output_dir: Path,
    worker_name: str,
    extra_args: list[str] | None = None,
) -> IngestionResult:
    """
    Run yt-dlp as a subprocess and return an IngestionResult.

    Args:
        url:         Media URL to download.
        output_dir:  Directory where files will be saved.
        worker_name: Worker class name for result attribution.
        extra_args:  Additional yt-dlp CLI flags (e.g. ['--cookies-from-browser', 'chrome']).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(title)s.%(ext)s")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--user-agent", CHROME_USER_AGENT,
        "--output", output_template,
        "--no-playlist",
        "--print", "after_move:filepath",  # Reliable filename extraction
        url,
    ]
    if extra_args:
        # Insert extra args before the URL (last element)
        cmd = cmd[:-1] + extra_args + [url]

    logger.debug("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return IngestionResult(
            success=False,
            url=url,
            worker_name=worker_name,
            error_code="YTDLP_NOT_FOUND",
            error_message="yt-dlp not found. Install with: pip install yt-dlp",
        )
    except Exception as exc:  # noqa: BLE001
        return IngestionResult(
            success=False,
            url=url,
            worker_name=worker_name,
            error_code="SUBPROCESS_ERROR",
            error_message=str(exc),
            stack_trace=traceback.format_exc(),
        )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        # Extract HTTP error code if present (e.g. "ERROR: HTTP Error 403: Forbidden")
        error_code = _extract_http_code(stderr) or str(result.returncode)
        logger.debug("yt-dlp stderr: %s", stderr)
        return IngestionResult(
            success=False,
            url=url,
            worker_name=worker_name,
            error_code=error_code,
            error_message=stderr or f"yt-dlp exited with code {result.returncode}",
        )

    # --print after_move:filepath writes the final path as the last non-empty line
    filename = _parse_filename(stdout)
    logger.debug("yt-dlp stdout: %s", stdout[:500])

    return IngestionResult(
        success=True,
        url=url,
        worker_name=worker_name,
        filename=filename,
    )


def _parse_filename(stdout: str) -> str | None:
    """Extract the downloaded filename from yt-dlp's stdout."""
    if not stdout:
        return None
    # --print after_move:filepath puts it as the last line
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if lines:
        candidate = lines[-1]
        # Sanity check: should look like a file path
        if candidate and not candidate.startswith("[") and not candidate.startswith("ERROR"):
            return candidate
    # Fallback: scan for Destination or Merger lines
    for line in reversed(stdout.splitlines()):
        m = _MERGER_RE.search(line) or _DEST_RE.search(line) or _ALREADY_RE.search(line)
        if m:
            return m.group(1).strip()
    return None


def _extract_http_code(stderr: str) -> str | None:
    """Pull out an HTTP status code string from yt-dlp error output."""
    m = re.search(r"HTTP Error (\d{3})", stderr, re.IGNORECASE)
    return m.group(1) if m else None
