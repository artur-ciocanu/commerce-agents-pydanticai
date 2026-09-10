from fastapi.testclient import TestClient

from commerce_agents.app import create_app
from commerce_agents.merchant import MerchantExecutor
from commerce_agents.retail import CATALOG


async def test_merchant_change_requires_host_approval_and_consumes_it() -> None:
    executor = MerchantExecutor(list(CATALOG), operator="operator-1")
    staged = await executor.execute(
        "stage_price_update", {"product_id": "TR-100", "new_price": 200}
    )
    change_id = staged.events[0].data["change"]["change_id"]

    blocked = await executor.execute("apply_change", {"change_id": change_id})
    executor.approve(change_id)
    applied = await executor.execute("apply_change", {"change_id": change_id})
    repeated = await executor.execute("apply_change", {"change_id": change_id})

    assert staged.events[0].data["change"]["status"] == "staged"
    assert blocked.blocked == "host_approval"
    assert applied.events[0].data["change"]["status"] == "applied"
    assert repeated.blocked == "host_approval"


async def test_merchant_guardrail_blocks_large_price_moves() -> None:
    executor = MerchantExecutor(list(CATALOG))
    outcome = await executor.execute(
        "stage_price_update", {"product_id": "TR-100", "new_price": 100}
    )

    assert outcome.blocked == "guardrail"
    assert "20% limit" in outcome.result_text


async def test_host_approval_endpoint_is_the_only_approval_path() -> None:
    app = create_app("test")
    with TestClient(app) as client:
        session_id = client.post("/api/merchant/session").json()["session_id"]
        host = app.state.retail_host
        session = host._sessions[("merchant", session_id)]
        assert session.merchant_executor is not None
        staged = await session.merchant_executor.execute(
            "stage_price_update", {"product_id": "TR-100", "new_price": 200}
        )
        change_id = staged.events[0].data["change"]["change_id"]
        response = client.post(
            f"/api/merchant/changes/{change_id}/approve", headers={"X-Session-Id": session_id}
        )
        applied = await session.merchant_executor.execute("apply_change", {"change_id": change_id})

    assert response.status_code == 200
    assert response.json()["change"]["status"] == "staged"
    assert applied.events[0].data["change"]["status"] == "applied"
