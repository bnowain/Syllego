"""
router.py — Priority-sorted worker dispatch engine.

Discovery: Router finds all BaseWorker subclasses that have been imported.
Workers are tried in ascending priority order. The first successful result wins.
Failed downloads get a history record + a failure bundle written to debug/.

AI-MAINTENANCE NOTE:
  To add a new worker: subclass BaseWorker in a new file, set priority, implement
  can_handle() and download(). Import the module here (bottom of this file) so
  the Router can discover it.
"""
from __future__ import annotations

from pathlib import Path

from mmi.config import MMI_OUTPUT_DIR, get_logger
from mmi.db import history as db
from mmi.engine.base import BaseWorker, IngestionResult
from mmi.reporting.reporter import write_failure_bundle

logger = get_logger("mmi.router")


class Router:
    """Discovers and dispatches to workers in priority order."""

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or MMI_OUTPUT_DIR
        self._workers: list[BaseWorker] | None = None

    # ------------------------------------------------------------------
    # Worker discovery
    # ------------------------------------------------------------------

    def _get_workers(self) -> list[BaseWorker]:
        """Lazy-load and sort all registered BaseWorker subclasses."""
        if self._workers is None:
            # Import all worker modules so subclasses register themselves
            _import_workers()
            subclasses = _all_subclasses(BaseWorker)
            # Exclude CustomWorker from auto-routing (it never handles via can_handle)
            self._workers = sorted(
                [cls() for cls in subclasses],
                key=lambda w: w.priority,
            )
            logger.debug(
                "Discovered workers: %s",
                [f"{w.__class__.__name__}({w.priority})" for w in self._workers],
            )
        return self._workers

    # ------------------------------------------------------------------
    # Public dispatch methods
    # ------------------------------------------------------------------

    def ingest(self, url: str) -> IngestionResult:
        """
        Auto-route URL to the highest-priority worker that can handle it.
        Records result in history DB; writes failure bundle on failure.
        """
        workers = self._get_workers()
        tried = []
        for worker in workers:
            if not worker.can_handle(url):
                continue
            logger.info("Trying %s for %s", type(worker).__name__, url)
            result = worker.safe_download(url, self.output_dir)
            tried.append(type(worker).__name__)
            if result.success:
                db.record_download(
                    url=url,
                    download_status="success",
                    worker_name=result.worker_name,
                    filename=result.filename,
                )
                logger.info("Success via %s → %s", result.worker_name, result.filename)
                return result
            else:
                logger.warning(
                    "%s failed (%s): %s",
                    type(worker).__name__,
                    result.error_code,
                    result.error_message,
                )

        # All matching workers failed — record the last failure
        last_result = result if tried else IngestionResult(
            success=False,
            url=url,
            worker_name="Router",
            error_code="NO_WORKER",
            error_message="No worker could handle this URL",
        )
        db.record_download(
            url=url,
            download_status="failed",
            worker_name=last_result.worker_name,
            error_message=last_result.error_message,
        )
        write_failure_bundle(last_result)
        return last_result

    def ingest_m3u8(self, stream_url: str, referer: str) -> IngestionResult:
        """
        Manual m3u8 override — always uses CustomWorker regardless of URL.
        """
        # Import here to avoid circular at module level
        from mmi.engine.custom_worker import CustomWorker
        worker = CustomWorker()
        result = worker.safe_download_m3u8(stream_url, referer, self.output_dir)
        status = "success" if result.success else "failed"
        db.record_download(
            url=stream_url,
            download_status=status,
            worker_name=result.worker_name,
            filename=result.filename,
            error_message=result.error_message,
        )
        if not result.success:
            write_failure_bundle(result)
        return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _all_subclasses(cls: type) -> list[type]:
    """Recursively collect all non-abstract subclasses of cls."""
    result = []
    for sub in cls.__subclasses__():
        if not getattr(sub, "__abstractmethods__", None):
            result.append(sub)
        result.extend(_all_subclasses(sub))
    return result


def _import_workers() -> None:
    """Import all worker modules so their classes register as BaseWorker subclasses."""
    # Order here doesn't matter — priority int determines dispatch order
    import mmi.engine.rumble_worker    # noqa: F401
    import mmi.engine.odysee_worker    # noqa: F401
    import mmi.engine.gallery_worker   # noqa: F401
    import mmi.engine.ytdlp_worker     # noqa: F401
    import mmi.engine.generic_worker   # noqa: F401
    # CustomWorker is NOT imported here — it's never auto-routed
