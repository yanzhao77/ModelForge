"""Logging configuration for ModelForge 2.0."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import load_config

# Keep the on-disk log bounded for long-running servers.
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
_HANDLER_MARK = "_modelforge_handler"


def setup_logging():
    """Configure application logging based on settings."""
    settings = load_config()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Ensure log directory exists
    log_dir = Path(__file__).resolve().parents[3] / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "modelforge.log"

    # Root logger
    logger = logging.getLogger("modelforge")
    logger.setLevel(level)

    # Calling this twice (an embedded server plus the desktop client, or a
    # test process) used to duplicate every line; drop our own handlers first.
    for existing in list(logger.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            logger.removeHandler(existing)
            existing.close()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    setattr(console, _HANDLER_MARK, True)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(console)

    # File handler
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    setattr(file_handler, _HANDLER_MARK, True)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    return logger
