from commerce_agents.reference.adapter import RetailBackendAdapter


async def test_transplanted_retail_backend_uses_source_catalog_and_policies() -> None:
    backend = RetailBackendAdapter("source-contract")

    products = await backend.search_products("tent", None, 8)
    assert products
    assert [product.product_id for product in products] == ["AR-1201", "AR-1202"]

    policies = await backend.search_policies("return")
    assert policies
