"""Source-compatible telecom plan-matrix presentation enrichment."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .events import AgentEvent


class PlanMatrixPayload(BaseModel):
    title: str = Field(max_length=80)
    product_ids: list[str] = Field(min_length=1, max_length=8)
    highlight_product_id: str | None = None


def enrich_plan_matrix(payload: dict[str, Any], products: dict[str, Any]) -> dict[str, Any]:
    matrix = PlanMatrixPayload.model_validate(payload)
    plans = [
        products[product_id].model_dump(mode="json")
        for product_id in matrix.product_ids
        if product_id in products
    ]
    result: dict[str, Any] = {"title": matrix.title, "plans": plans}
    if matrix.highlight_product_id in {plan["product_id"] for plan in plans}:
        result["highlight_product_id"] = matrix.highlight_product_id
    return result


def plan_matrix_partial(payload: dict[str, Any], products: dict[str, Any]) -> AgentEvent | None:
    try:
        enriched = enrich_plan_matrix(payload, products)
    except ValueError:
        return None
    return AgentEvent.ui_partial("plan_matrix", enriched)
