"""Contract-shaped stand-in for the desktop API client.

The QA scripts that drive the desktop client offscreen (``gui_exit_probe.py``,
``render_pages_offscreen.py``) need an ``api`` object whose *shape* matches
``ModelForgeClient``. Pages call ``payload.get(...)`` on dict payloads and
iterate list payloads, so a fake that answers ``[]`` to everything raises
inside Qt slots: the UI silently keeps its previous state and the QA script
still reports success.

``DesktopContractStub`` therefore derives its defaults from the real client's
return annotations, which keeps the fake honest as the client grows:

* every public ``ModelForgeClient`` method exists and answers with the shape the
  client promises (``dict`` → ``{}``, ``list[dict]`` → ``[]`` …);
* a handful of endpoints that pages render from get richer fixtures;
* calling a name the client does not have raises ``AttributeError`` instead of
  silently returning an empty list;
* every call is recorded, so a QA script can assert which endpoints the run
  actually touched.
"""

from __future__ import annotations

import inspect
import os
import sys
import types
import typing
from collections.abc import Callable
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
if CLIENT_ROOT not in sys.path:
    sys.path.insert(0, CLIENT_ROOT)

from api_client.client import ModelForgeClient  # noqa: E402


def _empty_for(annotation: Any) -> Any:
    """Default value that matches a return annotation's shape."""
    if annotation is inspect.Signature.empty or annotation is Any:
        return None
    origin = typing.get_origin(annotation)
    if origin in (list, tuple, set, frozenset):
        return []
    if origin is dict:
        return {}
    if origin in (typing.Union, types.UnionType):
        inner = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _empty_for(inner[0]) if inner else None
    if isinstance(annotation, type):
        if issubclass(annotation, bool):
            return False
        if issubclass(annotation, int):
            return 0
        if issubclass(annotation, float):
            return 0.0
        if issubclass(annotation, str):
            return ""
        if issubclass(annotation, dict):
            return {}
        if issubclass(annotation, (list, tuple, set, frozenset)):
            return []
    return None


def _return_defaults() -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for name, member in inspect.getmembers(ModelForgeClient, inspect.isfunction):
        if name.startswith("_"):
            continue
        try:
            hints = typing.get_type_hints(member)
        except Exception:  # pragma: no cover - defensive for exotic annotations
            hints = {}
        defaults[name] = _empty_for(hints.get("return", inspect.Signature.empty))
    return defaults


class DesktopContractStub:
    """Return-shape-faithful fake client with call recording."""

    username = "qa-desktop"
    base_url = "http://qa.local"

    def __init__(self, overrides: dict[str, Callable[..., Any]] | None = None):
        self.calls: list[str] = []
        self._overrides: dict[str, Callable[..., Any]] = dict(overrides or {})
        self._defaults = _return_defaults()
        self._defaults.update(
            {
                # Endpoints whose payload drives visible state; richer fixtures
                # keep the offscreen renders representative.
                "get_info": {"version": "0.1.3-beta.1", "edition": "3.0"},
                "system_status": {"status": "ok", "uptime_seconds": 3600},
                "get_download_source": {
                    "source": "official",
                    "endpoint": "https://huggingface.co",
                },
                "update_download_source": {
                    "source": "official",
                    "endpoint": "https://huggingface.co",
                },
                "model_readiness": {
                    # READY keeps the first-run wizard closed: it opens modally
                    # whenever the snapshot is not READY, which would stall a
                    # headless QA run inside its nested event loop.
                    "level": "READY",
                    "recommended_action": "open_chat",
                    "blocking_reasons": [],
                    "targets": [{"kind": "local", "model_name": "local-gguf"}],
                    "default_target": {"kind": "local", "model_name": "local-gguf"},
                },
                "task_summary": {
                    "total": 0,
                    "active": 0,
                    "needs_attention": 0,
                    "by_status": {},
                },
                "onboarding_state": {
                    "server_connected": True,
                    "ready_model_count": 0,
                    "has_sent_message": False,
                    "has_completed_agent_run": False,
                    "next_recommended_step": "select_model",
                },
                "runtime_status": {"runtimes": {}},
                "train_templates": {"lora": {}, "full": {}},
                "plugin_health": {"status": "ok", "plugins": []},
                "agent_metrics": {"runs": 0, "tools": 0},
                "model_insights": {"models": [], "insights": []},
                "control_plane_budget": {"budget": {}, "usage": {}},
                "lifecycle_diagnostics": {"checks": [], "status": "ok"},
            }
        )

    # -- attribute access -------------------------------------------------
    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._defaults:
            raise AttributeError(
                f"{type(self).__name__} has no endpoint {name!r}: "
                "ModelForgeClient does not define it, so the QA stub cannot "
                "mirror it either"
            )

        def endpoint(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            if name in self._overrides:
                return self._overrides[name](*args, **kwargs)
            return self._defaults[name]

        return endpoint

    # -- diagnostics ------------------------------------------------------
    def called_endpoints(self) -> list[str]:
        return sorted(set(self.calls))
