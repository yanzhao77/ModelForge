"""Phase 0: Verify ModelForge 2.0 project structure."""
import os


def test_client_pyside6_exists():
    """client/pyside6 directory should exist."""
    base = os.path.dirname(os.path.dirname(__file__))
    assert os.path.isdir(os.path.join(base, "client", "pyside6"))


def test_client_pyside6_subdirs():
    """client/pyside6 subdirectories should exist."""
    base = os.path.dirname(os.path.dirname(__file__))
    for sub in ["api_client", "pages", "components", "resources"]:
        path = os.path.join(base, "client", "pyside6", sub)
        assert os.path.isdir(path), f"Missing: {path}"


def test_backend_app_exists():
    """backend/app directory should exist."""
    base = os.path.dirname(os.path.dirname(__file__))
    assert os.path.isdir(os.path.join(base, "backend", "app"))


def test_backend_app_subdirs():
    """backend/app subdirectories should exist."""
    base = os.path.dirname(os.path.dirname(__file__))
    for sub in ["api", "services", "core", "plugins"]:
        path = os.path.join(base, "backend", "app", sub)
        assert os.path.isdir(path), f"Missing: {path}"


def test_tests_exists():
    """tests directory should exist."""
    base = os.path.dirname(os.path.dirname(__file__))
    assert os.path.isdir(os.path.join(base, "tests"))


def test_docs_exists():
    """docs directory should exist."""
    base = os.path.dirname(os.path.dirname(__file__))
    assert os.path.isdir(os.path.join(base, "docs"))
