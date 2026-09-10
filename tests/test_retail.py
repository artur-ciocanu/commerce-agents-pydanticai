from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from commerce_agents.app import RetailHost, create_app


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


async def test_retail_host_persists_pydanticai_history_per_session() -> None:
    host = RetailHost("test")
    session_id = host.start("shopping")
    seen_message_counts: list[int] = []

    def text_model(messages, _: AgentInfo):
        seen_message_counts.append(len(messages))
        return ModelResponse(parts=[TextPart("Noted.")])

    with host._agents["shopping"]._agent.override(model=FunctionModel(text_model)):
        await host.turn("shopping", session_id, "First message")
        await host.turn("shopping", session_id, "Second message")

    assert seen_message_counts[1] > seen_message_counts[0]
