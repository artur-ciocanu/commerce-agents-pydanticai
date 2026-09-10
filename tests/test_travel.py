from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from commerce_agents.app import create_app
from commerce_agents.reference.adapter import TravelBackendAdapter


async def test_travel_backend_searches_destination_and_preserves_cart() -> None:
    backend = TravelBackendAdapter("travel-contract")

    products = await backend.search_products("lisbon", None, 8)
    assert products

    product_id = products[0].product_id
    await backend.add_to_cart("session", product_id, 1)
    assert (await backend.get_cart("session")).items[0].product_id == product_id


def test_travel_api_uses_the_shared_sse_contract() -> None:
    app = create_app("test")
    host = app.state.retail_host

    def model(messages, _: AgentInfo) -> ModelResponse:
        if not any(
            isinstance(part, ToolCallPart) for message in messages for part in message.parts
        ):
            return ModelResponse(parts=[ToolCallPart("search_products", {"query": "Lisbon"})])
        return ModelResponse(parts=[TextPart("I found Lisbon options.")])

    with (
        host._agents["travel"]._agent.override(model=FunctionModel(model)),
        TestClient(app) as client,
    ):
        session = client.post("/api/travel/session").json()["session_id"]
        response = client.post(
            "/api/travel/chat", headers={"X-Session-Id": session}, json={"message": "Lisbon"}
        )

    assert response.status_code == 200
    assert "event: tool_call" in response.text
    assert "event: turn_complete" in response.text
