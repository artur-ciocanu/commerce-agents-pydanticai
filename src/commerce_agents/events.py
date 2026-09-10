"""The provider-independent event contract exposed to application hosts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventType = Literal[
    "text_delta",
    "tool_call",
    "tool_result",
    "ui",
    "ui_partial",
    "progress",
    "cart_update",
    "change_update",
    "turn_complete",
    "error",
]


@dataclass(frozen=True)
class AgentEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text_delta(cls, text: str) -> AgentEvent:
        return cls("text_delta", {"text": text})

    @classmethod
    def tool_call(cls, name: str, call_id: str, arguments: dict[str, Any]) -> AgentEvent:
        return cls("tool_call", {"tool": name, "id": call_id, "input": arguments})

    @classmethod
    def tool_result(cls, name: str, call_id: str, outcome: ToolOutcome) -> AgentEvent:
        return cls(
            "tool_result",
            {
                "tool": name,
                "id": call_id,
                "summary": outcome.result_text,
                "is_error": outcome.is_error,
                "status": "blocked" if outcome.blocked else ("error" if outcome.is_error else "ok"),
                "reason": outcome.blocked,
            },
        )

    @classmethod
    def complete(cls, usage: dict[str, int]) -> AgentEvent:
        return cls("turn_complete", {"usage": usage})

    @classmethod
    def error(cls, message: str) -> AgentEvent:
        return cls("error", {"message": message})

    @classmethod
    def ui_partial(cls, component: str, payload: dict[str, Any]) -> AgentEvent:
        return cls("ui_partial", {"component": component, "payload": payload})

    @classmethod
    def progress(cls, message: str) -> AgentEvent:
        return cls("progress", {"message": message[:140]})


@dataclass(frozen=True)
class ToolOutcome:
    """The executor result visible to both model and application host."""

    result_text: str
    events: tuple[AgentEvent, ...] = ()
    is_error: bool = False
    blocked: str | None = None
