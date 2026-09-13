"""Phase 11: Engineering tests."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


class TestLoggingConfig:
    def test_setup_logging(self):
        from core.logging_config import setup_logging
        logger = setup_logging()
        assert logger is not None
        assert logger.name == "modelforge"

    def test_setup_logging_is_idempotent_and_rotates(self):
        from logging.handlers import RotatingFileHandler

        from core.logging_config import LOG_BACKUP_COUNT, setup_logging

        logger = setup_logging()
        handlers = len(logger.handlers)
        # A second call must replace our handlers, not stack duplicates.
        setup_logging()
        assert len(logger.handlers) == handlers

        files = [handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)]
        assert files, "the log file must be bounded by a rotating handler"
        assert files[0].maxBytes > 0
        assert files[0].backupCount == LOG_BACKUP_COUNT


class TestDockerFiles:
    def test_dockerfile_exists(self):
        base = os.path.dirname(os.path.dirname(__file__))
        dockerfile = os.path.join(base, "Dockerfile")
        assert os.path.exists(dockerfile)

    def test_dockerignore_exists(self):
        base = os.path.dirname(os.path.dirname(__file__))
        dockerignore = os.path.join(base, ".dockerignore")
        assert os.path.exists(dockerignore)


class TestCIConfig:
    def test_ci_workflow_exists(self):
        base = os.path.dirname(os.path.dirname(__file__))
        ci_file = os.path.join(base, ".github", "workflows", "ci.yml")
        assert os.path.exists(ci_file)
