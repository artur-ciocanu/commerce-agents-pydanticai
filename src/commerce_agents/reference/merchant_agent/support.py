"""Minimal provider-neutral dependencies used by the vendored merchant contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

ThinkingEffort = Literal["low", "medium", "high"]
T = TypeVar("T")


class ClockContext(BaseModel):
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BaseAgentConfig(BaseModel):
    brand_name: str = "the store"
    max_fenced_chars: int = Field(default=12_000, ge=500)
    max_search_results: int = Field(default=8, ge=1)
    enable_web_search: bool = False


def remember(records: dict[str, T], key: str, value: T) -> None:
    records[key] = value


def truncate_display(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "..."
