from commerce_agents.reference.adapter import RetailBackendAdapter
from commerce_agents.shopping import ShoppingExecutor


async def test_transplanted_storefront_orders_use_the_source_session_contract() -> None:
    executor = ShoppingExecutor(RetailBackendAdapter("orders-contract"), "orders-contract")

    recent = await executor.execute("get_orders", {})
    assert "order_id" in recent.result_text
