from commerce_agents.shopping import Product
from commerce_agents.travel_presentation import enrich_itinerary, itinerary_partial


def test_itinerary_resolves_only_session_seen_products() -> None:
    products = {"stay": Product(product_id="stay", title="Stay", price=100)}
    payload = {"title": "Trip", "days": [{"label": "Day 1", "product_ids": ["stay", "unknown"]}]}

    enriched = enrich_itinerary(payload, products)
    partial = itinerary_partial(payload, products)

    assert [product["product_id"] for product in enriched["days"][0]["products"]] == ["stay"]
    assert partial is not None and partial.type == "ui_partial"
