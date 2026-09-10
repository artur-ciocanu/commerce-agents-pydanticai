from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from commerce_agents.app import create_app
from commerce_agents.retail import RetailExecutor


async def test_merchant_price_changes_are_staged_not_applied() -> None:
    executor = RetailExecutor()
    outcome = await executor.execute(
        "stage_price_update", {"product_id": "TR-100", "new_price": 199}
    )

    assert outcome.result_text == "Staged chg-0001 for host approval."
    assert executor.staged_changes == [
        {
            "change_id": "chg-0001",
            "product_id": "TR-100",
            "from_price": 229.0,
            "to_price": 199.0,
            "status": "staged",
        }
    ]
    assert outcome.events[0].type == "change_update"


def model(messages, info: AgentInfo):
    if not any(isinstance(part, ToolCallPart) for message in messages for part in message.parts):
        assert info.function_tools
        return ModelResponse(parts=[ToolCallPart("search_products", {"query": "tent"})])
    return ModelResponse(parts=[TextPart("I found the Trail Tent.")])


def test_retail_api_keeps_sse_contract() -> None:
    app = create_app("test")
    host = app.state.retail_host
    with (
        host._agents["shopping"]._agent.override(model=FunctionModel(model)),
        TestClient(app) as client,
    ):
        session = client.post("/api/session").json()["session_id"]
        response = client.post(
            "/api/chat", headers={"X-Session-Id": session}, json={"message": "tent"}
        )

    assert response.status_code == 200
    assert "event: tool_call" in response.text
    assert "event: turn_complete" in response.text
