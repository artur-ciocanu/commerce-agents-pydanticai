from commerce_agents.reference.adapter import TelecomBackendAdapter


async def test_transplanted_telecom_backend_uses_source_plan_catalog() -> None:
    backend = TelecomBackendAdapter("telecom-contract")

    plans = await backend.search_products("unlimited", None, 8)
    assert any(product.product_id == "AM-PLAN-103" for product in plans)

    await backend.add_to_cart("telecom-contract", "AM-PLAN-101", 1)
    await backend.add_to_cart("telecom-contract", "AM-PLAN-103", 1)
    cart = await backend.get_cart("telecom-contract")
    assert [item.product_id for item in cart.items] == ["AM-PLAN-103"]
