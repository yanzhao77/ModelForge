"""Logging configuration for ModelForge 2.0."""
import logging
import sys
from pathlib import Path

from .config import load_config


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

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    return logger
