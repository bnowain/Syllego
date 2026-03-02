"""
base.py — BaseWorker ABC and IngestionResult dataclass.

Every worker must:
  - Set class-level `priority: int` (lower = tried first)
  - Implement `can_handle(url) -> bool`
  - Implement `download(url, output_dir) -> IngestionResult`
  - Never raise from `download()` — catch internally and return a failed IngestionResult
"""
from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IngestionResult:
    """Returned by every worker's download() method."""
    success: bool
    url: str
    worker_name: str
    filename: str | None = None          # Relative or absolute path of saved file
    error_code: str | None = None        # HTTP status code or short error label
    error_message: str | None = None     # Human-readable error description
    stack_trace: str | None = None       # Full traceback string (populated on exception)
    page_html: str | None = None         # Page source fetched on failure (for bundles)
    metadata: dict = field(default_factory=dict)  # Any extra worker-specific data


class BaseWorker(ABC):
    """Abstract base for all MMI workers."""

    # Override in subclass — lower priority = tried first in the chain
    priority: int = 999

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this worker knows how to handle the given URL."""

    @abstractmethod
    def download(self, url: str, output_dir: Path) -> IngestionResult:
        """
        Download media from `url` into `output_dir`.

        MUST NOT raise — catch all exceptions internally and return a failed
        IngestionResult with error_message and stack_trace populated.
        """

    # ------------------------------------------------------------------
    # Convenience: safe wrapper in case a subclass slips and raises
    # ------------------------------------------------------------------
    def safe_download(self, url: str, output_dir: Path) -> IngestionResult:
        """Calls download() and catches any unexpected exception as a last resort."""
        try:
            return self.download(url, output_dir)
        except Exception as exc:  # noqa: BLE001
            return IngestionResult(
                success=False,
                url=url,
                worker_name=type(self).__name__,
                error_code="UNEXPECTED_EXCEPTION",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} priority={self.priority}>"
