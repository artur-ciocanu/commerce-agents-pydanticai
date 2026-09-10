"""Source-derived deterministic grounding decisions for provider-neutral turns."""

from __future__ import annotations

import re

_POLICY_TERMS = ("return", "refund", "exchange", "warranty", "cancel", "policy", "terms")
_ORDER_TERMS = ("order", "tracking", "shipment", "package", "delivery")
_QUESTION_CUES = ("?", "how", "what", "when", "where", "status", "track")
_PRODUCT_ID = re.compile(r"\b[A-Z]{2,4}(?:-[A-Z]{2,6})?-\d{3,4}(?:-[A-Z0-9]{2,6})?\b")


def shopping_grounding_tools(
    message: str, seen_product_ids: set[str]
) -> list[tuple[str, dict[str, str]]]:
    """Return source-precedence reads: policy, orders, then unresolved catalog id."""
    text = message.casefold()
    tools: list[tuple[str, dict[str, str]]] = []
    if any(term in text for term in _POLICY_TERMS) and any(cue in text for cue in _QUESTION_CUES):
        tools.append(("search_policies", {"query": message}))
    elif any(term in text for term in _ORDER_TERMS) and any(cue in text for cue in _QUESTION_CUES):
        tools.append(("get_orders", {}))
    if match := _PRODUCT_ID.search(message):
        product_id = match.group(0)
        if product_id.casefold() not in {item.casefold() for item in seen_product_ids}:
            tools.append(("get_product_details", {"product_id": product_id}))
    return tools
