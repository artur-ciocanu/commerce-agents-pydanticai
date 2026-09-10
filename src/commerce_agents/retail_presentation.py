"""Grounded retail card and comparison presentation payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .events import AgentEvent


class ProductCardsPayload(BaseModel):
    title: str = Field(max_length=80)
    product_ids: list[str] = Field(min_length=1, max_length=8)


def product_cards(payload: dict[str, Any], products: dict[str, Any]) -> AgentEvent:
    request = ProductCardsPayload.model_validate(payload)
    cards = [
        products[product_id].model_dump(mode="json")
        for product_id in request.product_ids
        if product_id in products
    ]
    return AgentEvent.ui_partial("product_cards", {"title": request.title, "products": cards})


def comparison(payload: dict[str, Any], products: dict[str, Any]) -> AgentEvent:
    request = ProductCardsPayload.model_validate(payload)
    rows = [
        products[product_id].model_dump(mode="json")
        for product_id in request.product_ids
        if product_id in products
    ]
    return AgentEvent.ui_partial("comparison", {"title": request.title, "products": rows})
