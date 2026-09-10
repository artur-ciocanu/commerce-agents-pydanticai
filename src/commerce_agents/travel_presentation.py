"""Source-compatible itinerary payload enrichment for the travel host."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .events import AgentEvent


class ItineraryDay(BaseModel):
    label: str = Field(max_length=80)
    note: str | None = Field(default=None, max_length=280)
    product_ids: list[str] = Field(default_factory=list, max_length=6)


class ItineraryPayload(BaseModel):
    title: str = Field(max_length=80)
    days: list[ItineraryDay] = Field(min_length=1, max_length=10)
    travel_dates: str | None = Field(default=None, max_length=60)


def enrich_itinerary(payload: dict[str, Any], products: dict[str, Any]) -> dict[str, Any]:
    """Resolve only session-seen ids, matching the source presentation provenance rule."""
    plan = ItineraryPayload.model_validate(payload)
    days = []
    for day in plan.days:
        entry: dict[str, Any] = {
            "label": day.label,
            "products": [
                products[product_id].model_dump(mode="json")
                for product_id in day.product_ids
                if product_id in products
            ],
        }
        if day.note:
            entry["note"] = day.note
        days.append(entry)
    result: dict[str, Any] = {"title": plan.title, "days": days}
    if plan.travel_dates:
        result["travel_dates"] = plan.travel_dates
    return result


def itinerary_partial(payload: dict[str, Any], products: dict[str, Any]) -> AgentEvent | None:
    days = payload.get("days")
    if not isinstance(days, list) or not days:
        return None
    try:
        enriched = enrich_itinerary({"title": payload.get("title", ""), "days": days}, products)
    except ValueError:
        return None
    return AgentEvent.ui_partial("itinerary", enriched)
