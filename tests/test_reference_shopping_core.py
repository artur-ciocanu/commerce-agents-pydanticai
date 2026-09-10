from commerce_agents.reference.shopping_agent import ShoppingAgentConfig, ShoppingSessionState
from commerce_agents.reference.shopping_agent.serialization import compact_product
from commerce_agents.reference.shopping_agent.types import Product


def test_vendored_shopping_contracts_preserve_cart_limits_and_serialization() -> None:
    config = ShoppingAgentConfig(max_quantity_per_item=3, max_cart_lines=7)
    product = Product(product_id="SKU-1", title="Example", price=12.0, options={"color": ["blue"]})

    assert config.max_quantity_per_item == 3
    assert ShoppingSessionState().seen_products == {}
    assert compact_product(product)["product_id"] == "SKU-1"
