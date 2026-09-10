from commerce_agents.shopping import Product
from commerce_agents.telecom_presentation import enrich_plan_matrix, plan_matrix_partial


def test_plan_matrix_uses_only_seen_products() -> None:
    products = {"plan": Product(product_id="plan", title="Plan", price=30)}
    payload = {
        "title": "Compare",
        "product_ids": ["plan", "invented"],
        "highlight_product_id": "plan",
    }

    enriched = enrich_plan_matrix(payload, products)
    partial = plan_matrix_partial(payload, products)

    assert [plan["product_id"] for plan in enriched["plans"]] == ["plan"]
    assert enriched["highlight_product_id"] == "plan"
    assert partial is not None and partial.type == "ui_partial"
