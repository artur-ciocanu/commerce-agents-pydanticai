from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from commerce_agents import CommerceAgent, ToolContract, ToolOutcome


class Executor:
    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        assert name == "search_products"
        assert arguments == {"query": "tent"}
        return ToolOutcome("One matching tent")


class FailingExecutor:
    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        raise RuntimeError(f"{name} is unavailable")


class EmptyExecutor:
    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        assert name == "search_products"
        assert arguments == {}
        return ToolOutcome("No matches")


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


async def test_invalid_schema_arguments_retry_without_reaching_executor() -> None:
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
    calls = 0

    def retrying_model(_: list, __: AgentInfo):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart("search_products", {"query": 4})])
        if calls == 2:
            return ModelResponse(parts=[ToolCallPart("search_products", {"query": "tent"})])
        return ModelResponse(parts=[TextPart("The Trail Tent is available.")])

    with agent._agent.override(model=FunctionModel(retrying_model)):
        text, _, events = await agent.run("Find a tent", executor=Executor())

    assert text == "The Trail Tent is available."
    assert [event.type for event in events] == ["tool_call", "tool_result", "turn_complete"]


async def test_executor_errors_are_reported_as_tool_results() -> None:
    agent = CommerceAgent(
        model="test",
        instructions="Help customers shop.",
        tools=[
            ToolContract(
                name="search_products",
                description="Search products.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ],
    )

    def model_with_failure(messages, _: AgentInfo):
        if not any(
            isinstance(part, ToolCallPart) for message in messages for part in message.parts
        ):
            return ModelResponse(parts=[ToolCallPart("search_products", {})])
        return ModelResponse(parts=[TextPart("Please try again later.")])

    with agent._agent.override(model=FunctionModel(model_with_failure)):
        _, _, events = await agent.run("Search", executor=FailingExecutor())

    assert events[1].data["is_error"] is True


async def test_provider_limit_failures_preserve_the_host_event_contract() -> None:
    agent = CommerceAgent(
        model="test",
        instructions="Help customers shop.",
        tools=[
            ToolContract(
                name="search_products",
                description="Search products.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ],
        max_requests=1,
        max_tool_calls=1,
    )

    with agent._agent.override(
        model=FunctionModel(
            lambda _, __: ModelResponse(parts=[ToolCallPart("search_products", {})])
        )
    ):
        text, history, events = await agent.run("Search", executor=EmptyExecutor())

    assert text == ""
    assert history == []
    assert [event.type for event in events] == [
        "tool_call",
        "tool_result",
        "error",
        "turn_complete",
    ]
