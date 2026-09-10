from commerce_agents.reference.adapter import RetailBackendAdapter
from commerce_agents.shopping import ShoppingExecutor


async def test_source_product_family_cannot_bypass_variant_selection() -> None:
    executor = ShoppingExecutor(RetailBackendAdapter("variant-contract"), "variant-contract")
    family = (await executor.execute("search_products", {"query": "mattress"})).result_text
    assert "options" in family

    product_id = next(iter(executor.state.seen_products))
    outcome = await executor.execute("add_to_cart", {"product_id": product_id, "quantity": 1})
    assert outcome.blocked == "variant_selection"
