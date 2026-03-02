"""
cli.py — MMI command-line interface.

Usage:
  mmi <url>                              Auto-route to best worker
  mmi --m3u8 <stream> --referer <page>  Manual m3u8 stream download
  mmi --history                          Show recent downloads
  mmi --harvest-cookies                  Run Playwright cookie harvester
  mmi -o /path/to/dir <url>             Override output directory
  mmi -v <url>                           Verbose/debug logging
  mmi --version                          Print version and exit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mmi.config import MMI_OUTPUT_DIR, get_logger

_VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mmi",
        description="Modular Media Ingestor — download media from anywhere.",
    )
    p.add_argument("url", nargs="?", help="URL to download")
    p.add_argument("--m3u8", metavar="STREAM_URL", help="HLS m3u8 stream URL (manual override)")
    p.add_argument("--referer", metavar="PAGE_URL", help="Referer page URL (required with --m3u8)")
    p.add_argument("--history", action="store_true", help="Show recent download history")
    p.add_argument("--harvest-cookies", action="store_true", help="Run Playwright cookie harvester (helps with Rumble etc.)")
    p.add_argument("-o", "--output", metavar="DIR", help="Output directory (default: ./downloads)")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    p.add_argument("--version", action="version", version=f"mmi {_VERSION}")
    return p


def main() -> None:
    parser = build_parser()
    # Ensure stdout/stderr handle Unicode on Windows (filenames can contain emoji/CJK)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = parser.parse_args()

    logger = get_logger("mmi.cli", verbose=args.verbose)

    # Resolve output directory
    output_dir = Path(args.output) if args.output else MMI_OUTPUT_DIR

    # --history
    if args.history:
        _show_history()
        return

    # --harvest-cookies
    if args.harvest_cookies:
        from mmi.cookie_harvest import harvest_cookies
        cookies_path = harvest_cookies()
        print(f"Cookies saved: {cookies_path}")
        return

    # --m3u8 path
    if args.m3u8:
        if not args.referer:
            parser.error("--m3u8 requires --referer <page_url>")
        from mmi.engine.router import Router
        router = Router(output_dir=output_dir)
        result = router.ingest_m3u8(args.m3u8, args.referer)
        _print_result(result, verbose=args.verbose)
        sys.exit(0 if result.success else 1)

    # Auto-route URL
    if not args.url:
        parser.print_help()
        sys.exit(1)

    from mmi.engine.router import Router
    router = Router(output_dir=output_dir)
    result = router.ingest(args.url)
    _print_result(result, verbose=args.verbose)
    sys.exit(0 if result.success else 1)


def _show_history() -> None:
    from mmi.db.history import get_recent
    rows = get_recent(limit=20)
    if not rows:
        print("No downloads recorded yet.")
        return
    print(f"{'ID':<5} {'Status':<10} {'Worker':<20} {'Timestamp':<22} URL")
    print("-" * 100)
    for r in rows:
        status = r["download_status"]
        worker = (r["worker_name"] or "-")[:19]
        ts = (r["timestamp"] or "-")[:21]
        url = r["url"][:60]
        print(f"{r['id']:<5} {status:<10} {worker:<20} {ts:<22} {url}")


def _print_result(result, verbose: bool = False) -> None:
    if result.success:
        print(f"\n[OK] Downloaded via {result.worker_name}")
        if result.filename:
            print(f"     Saved to: {result.filename}")
    else:
        print(f"\n[FAIL] {result.worker_name}: {result.error_message}", file=sys.stderr)
        if verbose and result.stack_trace:
            print(result.stack_trace, file=sys.stderr)


if __name__ == "__main__":
    main()
