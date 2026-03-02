"""
mmi — Modular Media Ingestor

Public API:
  mmi.ingest(url)                          → IngestionResult
  mmi.ingest_m3u8(stream_url, referer)     → IngestionResult

The Router is lazy — no DB or filesystem access until first call.
"""
from __future__ import annotations

from pathlib import Path

from mmi.engine.base import IngestionResult  # re-export for consumers

__version__ = "0.1.0"
__all__ = ["ingest", "ingest_m3u8", "IngestionResult"]

_router = None  # Lazy singleton


def _get_router(output_dir: Path | None = None):
    global _router
    if _router is None or output_dir is not None:
        from mmi.engine.router import Router
        _router = Router(output_dir=output_dir)
    return _router


def ingest(url: str, output_dir: Path | None = None) -> IngestionResult:
    """
    Download media from `url` using the highest-priority matching worker.

    Args:
        url:        Media page URL.
        output_dir: Where to save files. Defaults to MMI_OUTPUT_DIR (./downloads).

    Returns:
        IngestionResult with success=True and filename set on success,
        or success=False with error details on failure.
    """
    return _get_router(output_dir).ingest(url)


def ingest_m3u8(
    stream_url: str,
    referer: str,
    output_dir: Path | None = None,
) -> IngestionResult:
    """
    Download an HLS m3u8 stream manually (bypasses auto-routing).

    Args:
        stream_url: The .m3u8 playlist URL.
        referer:    The page URL to send as Referer header.
        output_dir: Where to save files. Defaults to MMI_OUTPUT_DIR.

    Returns:
        IngestionResult.
    """
    return _get_router(output_dir).ingest_m3u8(stream_url, referer)
