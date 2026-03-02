"""
config.py — Global constants and logger factory for MMI.
All paths resolve relative to MMI_OUTPUT_DIR (env var or CWD/downloads).
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Output directory: env override or CWD/downloads
MMI_OUTPUT_DIR = Path(os.environ.get("MMI_OUTPUT_DIR", Path.cwd() / "downloads"))

# Subdirectory for failure bundles
MMI_DEBUG_DIR = MMI_OUTPUT_DIR / "debug"

# SQLite DB path (lives inside output dir — move folder, history follows)
MMI_DB_PATH = MMI_OUTPUT_DIR / "mmi_history.db"

# Log directory — fixed to the project root so it's always in the same place
# regardless of which app calls mmi or what their CWD is.
MMI_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# Optional caller tag — set os.environ["MMI_CALLER"] = "MyApp" before importing
# mmi so log entries show which application made the request.
# Does not affect the call signature of ingest() at all.
MMI_CALLER = os.environ.get("MMI_CALLER", "unknown")

# User-agent that works on most sites
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# ---------------------------------------------------------------------------
# Always-on file logging — scoped exclusively to the mmi.* logger namespace.
#
# Writes to:  <project_root>/logs/mmi_YYYY-MM-DD.log  (daily rotation, 30 days)
# Attached to logging.getLogger("mmi") only — the root logger and every other
# application's loggers are completely untouched. Safe to use inside any venv.
# ---------------------------------------------------------------------------
MMI_LOG_DIR.mkdir(parents=True, exist_ok=True)
_file_handler = TimedRotatingFileHandler(
    MMI_LOG_DIR / "mmi.log",
    when="midnight",
    backupCount=30,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
_file_handler.setLevel(logging.DEBUG)
# Attach only to the mmi namespace root — all mmi.* child loggers propagate here
# without touching the root logger or any other application's logging config.
logging.getLogger("mmi").addHandler(_file_handler)


def get_logger(name: str, verbose: bool = False) -> logging.Logger:
    """Return a named logger. Call once per module at import time or pass verbose flag."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    return logger
