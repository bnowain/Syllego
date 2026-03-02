"""
reporter.py — Failure bundle exporter.

Writes JSON files to MMI_DEBUG_DIR so failed downloads can be inspected
or fed to an AI for self-healing diagnosis.

Bundle filename: failure_bundle_{ISO8601_timestamp}.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mmi.config import MMI_DEBUG_DIR, get_logger
from mmi.engine.base import IngestionResult

logger = get_logger("mmi.reporter")


def write_failure_bundle(result: IngestionResult, debug_dir: Path = MMI_DEBUG_DIR) -> Path:
    """
    Write a failure bundle JSON for a failed IngestionResult.

    Returns the path to the written file.
    Does not raise — logs and returns a dummy path on error.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    debug_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = debug_dir / f"failure_bundle_{ts}.json"

    bundle = {
        "url": result.url,
        "worker": result.worker_name,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "stack_trace": result.stack_trace,
        "page_html": result.page_html,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "metadata": result.metadata,
    }

    try:
        with open(bundle_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
        logger.info("Failure bundle written: %s", bundle_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write failure bundle: %s", exc)

    return bundle_path
