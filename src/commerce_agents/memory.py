"""Application-owned, session-scoped memory with strict write filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .fencing import Fence
from .guardrails import redact_sensitive_text

MEMORY_FENCE = Fence("saved_memory")
_KEY = re.compile(r"[^a-z0-9_]+")


class MemoryWriteRejected(ValueError):
    """Raised when a proposed durable fact contains sensitive data."""


@dataclass
class SessionMemory:
    """Host-held facts that survive turns in one session but never bypass filtering."""

    facts: dict[str, str] = field(default_factory=dict)

    def save(self, key: str, value: str) -> str:
        normalized_key = _KEY.sub("_", key.strip().lower())[:64].strip("_")
        normalized_value = MEMORY_FENCE.sanitize_text(value, 240).strip()
        if not normalized_key or not normalized_value:
            raise MemoryWriteRejected("Memory needs a non-empty key and value.")
        if redact_sensitive_text(f"{normalized_key} {normalized_value}") != (
            f"{normalized_key} {normalized_value}"
        ):
            raise MemoryWriteRejected("Sensitive data cannot be saved to memory.")
        self.facts[normalized_key] = normalized_value
        return normalized_key

    def context(self) -> str:
        return MEMORY_FENCE.fence_payload({"facts": self.facts or "none"}, max_chars=2_000)
