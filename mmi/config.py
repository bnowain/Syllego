"""
config.py — Global constants and logger factory for MMI.
All paths resolve relative to MMI_OUTPUT_DIR (env var or CWD/downloads).
"""
import logging
import os
from pathlib import Path

# Output directory: env override or CWD/downloads
MMI_OUTPUT_DIR = Path(os.environ.get("MMI_OUTPUT_DIR", Path.cwd() / "downloads"))

# Subdirectory for failure bundles
MMI_DEBUG_DIR = MMI_OUTPUT_DIR / "debug"

# SQLite DB path (lives inside output dir — move folder, history follows)
MMI_DB_PATH = MMI_OUTPUT_DIR / "mmi_history.db"

# User-agent that works on most sites
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def get_logger(name: str, verbose: bool = False) -> logging.Logger:
    """Return a named logger. Call once per module at import time or pass verbose flag."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        logger.addHandler(handler)
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    return logger
