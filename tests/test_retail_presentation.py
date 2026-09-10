from commerce_agents.retail_presentation import comparison, product_cards
from commerce_agents.shopping import Product


def test_retail_presentation_only_resolves_seen_products() -> None:
    products = {"sku": Product(product_id="sku", title="Item", price=10)}
    payload = {"title": "Results", "product_ids": ["sku", "invented"]}

    cards = product_cards(payload, products)
    matrix = comparison(payload, products)

    assert [product["product_id"] for product in cards.data["payload"]["products"]] == ["sku"]
    assert matrix.data["component"] == "comparison"
