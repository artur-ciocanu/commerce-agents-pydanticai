"""Provider-neutral UI payload helpers for source-compatible SSE presentation events."""

from __future__ import annotations

from typing import Any

from .events import AgentEvent


def ui_partial(component: str, payload: dict[str, Any]) -> AgentEvent:
    """Return a host-renderable partial UI update without model-controlled markup."""
    return AgentEvent.ui_partial(component, payload)


def progress(message: str) -> AgentEvent:
    """Return a bounded host progress update."""
    return AgentEvent.progress(message)
