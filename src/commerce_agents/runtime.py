"""PydanticAI adapter for commerce tool contracts.

The adapter deliberately has no provider SDK imports. PydanticAI resolves a model string to the
configured provider, while application code owns all commerce data and side effects through an
executor.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic_ai import Agent, ModelRetry, RunContext, Tool, UsageLimits
from pydantic_ai.messages import ModelMessage

from .events import AgentEvent, ToolOutcome

logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    """Application-owned boundary for all commerce backend operations."""

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome: ...


@dataclass(frozen=True)
class ToolContract:
    """A model-visible tool definition shared by shopping and merchant roles."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class CommerceDependencies:
    executor: ToolExecutor
    host_events: list[AgentEvent] = field(default_factory=list)


def _tool(contract: ToolContract) -> Tool[CommerceDependencies]:
    """Adapt an existing JSON Schema contract without reimplementing it as Python types."""

    validator = Draft202012Validator(contract.input_schema)

    async def validate(_: RunContext[CommerceDependencies], **arguments: Any) -> None:
        if errors := list(validator.iter_errors(arguments)):
            detail = "; ".join(error.message for error in errors[:3])
            raise ModelRetry(f"{contract.name} arguments are invalid: {detail}")

    async def invoke(ctx: RunContext[CommerceDependencies], **arguments: Any) -> str:
        call_id = ctx.tool_call_id or f"call_{uuid4().hex}"
        payload = dict(arguments)
        ctx.deps.host_events.append(AgentEvent.tool_call(contract.name, call_id, payload))
        try:
            outcome = await ctx.deps.executor.execute(contract.name, payload)
        except Exception:  # noqa: BLE001 - backend failures are converted into tool outcomes.
            # A backend failure is model-visible but never aborts a persisted conversation.
            outcome = ToolOutcome(
                "This commerce operation is temporarily unavailable.", is_error=True
            )
        ctx.deps.host_events.extend(outcome.events)
        ctx.deps.host_events.append(AgentEvent.tool_result(contract.name, call_id, outcome))
        return outcome.result_text

    return Tool.from_schema(
        function=invoke,
        name=contract.name,
        description=contract.description,
        json_schema=contract.input_schema,
        takes_ctx=True,
        args_validator=validate,
    )


class CommerceAgent:
    """One role-specific agent with provider-independent tools and event output."""

    def __init__(
        self,
        *,
        model: str,
        instructions: str,
        tools: Sequence[ToolContract],
        max_requests: int = 17,
        max_tool_calls: int = 32,
    ) -> None:
        self._agent = Agent(
            model,
            deps_type=CommerceDependencies,
            instructions=instructions,
            tools=[_tool(contract) for contract in tools],
        )
        self._limits = UsageLimits(
            request_limit=max_requests,
            tool_calls_limit=max_tool_calls,
        )

    async def run(
        self,
        prompt: str,
        *,
        executor: ToolExecutor,
        message_history: list[ModelMessage] | None = None,
    ) -> tuple[str, list[ModelMessage], list[AgentEvent]]:
        deps = CommerceDependencies(executor)
        try:
            result = await self._agent.run(
                prompt,
                deps=deps,
                message_history=message_history,
                usage_limits=self._limits,
            )
        except Exception:
            logger.exception("commerce agent run failed")
            deps.host_events.extend(
                [
                    AgentEvent.error("The agent could not complete this turn. Please try again."),
                    AgentEvent.complete({"input_tokens": 0, "output_tokens": 0, "requests": 0}),
                ]
            )
            return "", message_history or [], deps.host_events
        usage = result.usage
        deps.host_events.append(
            AgentEvent.complete(
                {
                    "input_tokens": usage.input_tokens or 0,
                    "output_tokens": usage.output_tokens or 0,
                    "requests": usage.requests,
                }
            )
        )
        return str(result.output), result.all_messages(), deps.host_events

    async def stream_turn(
        self,
        prompt: str,
        *,
        executor: ToolExecutor,
        message_history: list[ModelMessage] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Yield the stable host protocol while retaining PydanticAI message history.

        PydanticAI executes tools before producing final text; tool events are therefore emitted
        before the final text event. Hosts persist the returned history through ``run``.
        """
        text, _, events = await self.run(prompt, executor=executor, message_history=message_history)
        for event in events:
            if event.type != "turn_complete":
                yield event
        if text:
            yield AgentEvent.text_delta(text)
        yield next(event for event in events if event.type == "turn_complete")
