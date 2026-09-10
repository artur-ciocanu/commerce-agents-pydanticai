from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from commerce_agents import CommerceAgent, ToolContract, ToolOutcome


class Executor:
    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        assert name == "search_products"
        assert arguments == {"query": "tent"}
        return ToolOutcome("One matching tent")


def model(messages, info: AgentInfo):
    if not any(isinstance(part, ToolCallPart) for message in messages for part in message.parts):
        assert (
            info.function_tools[0].parameters_json_schema["properties"]["query"]["type"] == "string"
        )
        return ModelResponse(parts=[ToolCallPart("search_products", {"query": "tent"})])
    return ModelResponse(parts=[TextPart("The Trail Tent is available.")])


async def test_contract_schema_and_host_events_are_provider_independent() -> None:
    agent = CommerceAgent(
        model="test",
        instructions="Help customers shop.",
        tools=[
            ToolContract(
                name="search_products",
                description="Search products.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            )
        ],
    )
    with agent._agent.override(model=FunctionModel(model)):
        text, history, events = await agent.run("Find a tent", executor=Executor())

    assert text == "The Trail Tent is available."
    assert history
    assert [event.type for event in events] == ["tool_call", "tool_result", "turn_complete"]
