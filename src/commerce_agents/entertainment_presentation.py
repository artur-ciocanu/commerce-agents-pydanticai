"""Host-owned ticketing presentation payloads for live venue and hold state."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .events import AgentEvent


class HoldViewPayload(BaseModel):
    product_ids: list[str] = Field(min_length=1, max_length=8)


def hold_view(payload: dict[str, Any], products: dict[str, Any]) -> AgentEvent:
    request = HoldViewPayload.model_validate(payload)
    tickets = [
        products[product_id].model_dump(mode="json")
        for product_id in request.product_ids
        if product_id in products
    ]
    return AgentEvent.ui_partial("hold_view", {"tickets": tickets})


def event_pacing(payload: dict[str, Any]) -> AgentEvent:
    """Relay backend-computed pacing only; models cannot supply counts or baselines."""
    return AgentEvent.ui_partial("event_pacing", payload)
