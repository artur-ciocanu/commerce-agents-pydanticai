from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from commerce_agents import (
    CommerceAgent,
    MemoryWriteRejected,
    SessionMemory,
    ToolContract,
    ToolOutcome,
)


class Executor:
    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        assert name == "lookup"
        assert arguments == {}
        return ToolOutcome("Customer email is customer@example.com")


async def test_harness_redacts_prompt_tool_result_and_output() -> None:
    agent = CommerceAgent(
        model="test",
        instructions="Help safely.",
        tools=[
            ToolContract(
                name="lookup",
                description="Look up a record.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ],
    )

    def model(messages, _: AgentInfo):
        text = str(messages)
        assert "customer@example.com" not in text
        assert "[redacted]" in text
        if not any(
            isinstance(part, ToolCallPart) for message in messages for part in message.parts
        ):
            return ModelResponse(parts=[ToolCallPart("lookup", {})])
        return ModelResponse(parts=[TextPart("Contact customer@example.com")])

    with agent._agent.override(model=FunctionModel(model)):
        text, _, _ = await agent.run("Use customer@example.com", executor=Executor())

    assert text == "Contact [redacted]"


async def test_save_memory_tool_uses_the_host_owned_store() -> None:
    agent = CommerceAgent(
        model="test",
        instructions="Help safely.",
        tools=[
            ToolContract(
                name="save_memory",
                description="Save a preference.",
                input_schema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
            )
        ],
    )
    memory = SessionMemory()

    def model(messages, _: AgentInfo):
        if not any(
            isinstance(part, ToolCallPart) for message in messages for part in message.parts
        ):
            return ModelResponse(parts=[ToolCallPart("save_memory", {"key": "size", "value": "M"})])
        return ModelResponse(parts=[TextPart("Saved.")])

    with agent._agent.override(model=FunctionModel(model)):
        await agent.run("I prefer medium", executor=Executor(), memory=memory)

    assert memory.facts == {"size": "M"}


def test_session_memory_rejects_sensitive_values_and_fences_context() -> None:
    memory = SessionMemory()

    assert memory.save("preferred color", "blue") == "preferred_color"
    assert "blue" in memory.context()
    assert memory.context().startswith("<saved_memory>")

    try:
        memory.save("card", "4111 1111 1111 1111")
    except MemoryWriteRejected:
        pass
    else:
        raise AssertionError("sensitive memory write was accepted")
