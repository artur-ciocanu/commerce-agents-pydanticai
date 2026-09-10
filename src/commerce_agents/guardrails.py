"""Model-facing data redaction capabilities layered over host controls."""

from __future__ import annotations

import re
from typing import Any

from pydantic_ai_harness import GuardrailResult, InputGuardrail, OutputGuardrail, ToolGuardrail
from pydantic_ai_harness.guardrails import ToolResultInfo

_SENSITIVE = re.compile(
    r"(?ix)"
    r"\b(?:sk|pk|rk)_[a-z0-9_-]{16,}\b"
    r"|\b(?:api[_-]?key|authorization|bearer)\s*[:=]\s*[^\s,;]+"
    r"|\b\d{3}-\d{2}-\d{4}\b"
    r"|\b(?:\d[ -]*?){13,19}\b"
    r"|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)


def redact_sensitive_text(text: str) -> str:
    """Remove data that should neither enter model history nor reach a caller."""
    return _SENSITIVE.sub("[redacted]", text)


class StreamingRedactor:
    """Delay a small suffix so patterns split across model chunks cannot leak."""

    def __init__(self, suffix_chars: int = 256) -> None:
        self._suffix_chars = suffix_chars
        self._buffer = ""

    def feed(self, text: str) -> str:
        self._buffer += text
        if len(self._buffer) <= self._suffix_chars:
            return ""
        safe, self._buffer = (
            self._buffer[: -self._suffix_chars],
            self._buffer[-self._suffix_chars :],
        )
        return redact_sensitive_text(safe)

    def finish(self) -> str:
        text, self._buffer = self._buffer, ""
        return redact_sensitive_text(text)


def _redact(value: Any) -> GuardrailResult:
    if not isinstance(value, str):
        return GuardrailResult.allow()
    cleaned = redact_sensitive_text(value)
    return GuardrailResult.replace(cleaned) if cleaned != value else GuardrailResult.allow()


def _redact_tool_result(info: ToolResultInfo) -> GuardrailResult:
    return _redact(info.result)


def commerce_guardrails() -> list[object]:
    """Return ordered capability boundaries for prompts, tool results, and output."""
    return [
        InputGuardrail(guard=_redact),
        ToolGuardrail(result_guard=_redact_tool_result),
        OutputGuardrail(guard=_redact),
    ]
