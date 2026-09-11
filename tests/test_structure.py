"""Phase 0: Verify ModelForge 2.0 project structure."""
import json
import os
import re


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


def test_every_navigation_entry_has_a_page_icon_and_translation():
    """A navigation entry without a destination is a dead link in the shell."""
    base = os.path.dirname(os.path.dirname(__file__))
    client = os.path.join(base, "client", "pyside6")
    shell = open(os.path.join(client, "components", "app_shell.py"), encoding="utf-8").read()
    main = open(os.path.join(client, "main.py"), encoding="utf-8").read()
    icons = open(os.path.join(client, "theme", "icons.py"), encoding="utf-8").read()

    groups = re.search(r"GROUPS = \((.*?)\n\s*\)", shell, re.S)
    assert groups is not None, "NavigationRail.GROUPS was not found"
    entries = set(re.findall(r'"([a-z_]+)"', groups.group(1)))
    # Guard the guard: a silently empty match would make this test meaningless.
    assert len(entries) >= 14, f"Suspiciously few navigation entries: {sorted(entries)}"

    pages_block = re.search(r"self\._pages = \{(.*?)\n\s*\}", main, re.S)
    assert pages_block is not None, "MainWindow._pages was not found"
    pages = set(re.findall(r'^\s*"([a-z_]+)":', pages_block.group(1), re.M))
    pages.add("tasks")  # handled by the task-center dock instead of the stack
    assert not entries - pages, f"Navigation entries without a page: {sorted(entries - pages)}"

    missing_icons = {entry for entry in entries if f'"{entry}"' not in icons}
    assert not missing_icons, f"Navigation entries without an icon: {sorted(missing_icons)}"

    for locale in ("zh_CN", "en_US", "ja_JP"):
        with open(os.path.join(client, "i18n", f"{locale}.json"), encoding="utf-8") as handle:
            strings = json.load(handle)
        missing = {entry for entry in entries if f"nav.{entry}" not in strings}
        assert not missing, f"{locale} is missing navigation labels: {sorted(missing)}"
