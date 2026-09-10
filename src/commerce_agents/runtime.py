"""PydanticAI adapter for commerce tool contracts.

The adapter deliberately has no provider SDK imports. PydanticAI resolves a model string to the
configured provider, while application code owns all commerce data and side effects through an
executor.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic_ai import Agent, ModelRetry, RunContext, Tool, UsageLimits
from pydantic_ai.messages import ModelMessage, PartDeltaEvent, TextPartDelta

from .events import AgentEvent, ToolOutcome
from .guardrails import StreamingRedactor, commerce_guardrails
from .memory import SessionMemory

logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    """Application-owned boundary for all commerce backend operations."""

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome: ...


class AnalysisDelegate(Protocol):
    """A host-owned subagent with no authority beyond an executor's read surface."""

    async def run(self, executor: ToolExecutor, arguments: dict[str, Any]) -> ToolOutcome: ...


@dataclass(frozen=True)
class ToolContract:
    """A model-visible tool definition shared by shopping and merchant roles."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class CommerceDependencies:
    executor: ToolExecutor
    memory: SessionMemory | None = None
    analysis: AnalysisDelegate | None = None
    host_events: list[AgentEvent] = field(default_factory=list)
    event_sink: Callable[[AgentEvent], None] | None = None

    def emit(self, event: AgentEvent) -> None:
        self.host_events.append(event)
        if self.event_sink is not None:
            self.event_sink(event)


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
        ctx.deps.emit(AgentEvent.tool_call(contract.name, call_id, payload))
        try:
            if contract.name == "save_memory":
                if ctx.deps.memory is None:
                    outcome = ToolOutcome("Memory is not enabled for this session.", is_error=True)
                else:
                    saved_key = ctx.deps.memory.save(str(payload["key"]), str(payload["value"]))
                    outcome = ToolOutcome(f"Saved memory: {saved_key}.")
            elif contract.name == "run_analysis":
                if ctx.deps.analysis is None:
                    outcome = ToolOutcome("Analysis is not enabled for this role.", is_error=True)
                else:
                    outcome = await ctx.deps.analysis.run(ctx.deps.executor, payload)
            else:
                outcome = await ctx.deps.executor.execute(contract.name, payload)
        except Exception:  # noqa: BLE001 - backend failures are converted into tool outcomes.
            # A backend failure is model-visible but never aborts a persisted conversation.
            outcome = ToolOutcome(
                "This commerce operation is temporarily unavailable.", is_error=True
            )
        for event in outcome.events:
            ctx.deps.emit(event)
        ctx.deps.emit(AgentEvent.tool_result(contract.name, call_id, outcome))
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
        analysis: AnalysisDelegate | None = None,
        max_requests: int = 17,
        max_tool_calls: int = 32,
    ) -> None:
        self._agent = Agent(
            model,
            deps_type=CommerceDependencies,
            instructions=instructions,
            tools=[_tool(contract) for contract in tools],
            capabilities=commerce_guardrails(),
        )
        self._analysis = analysis
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
        memory: SessionMemory | None = None,
    ) -> tuple[str, list[ModelMessage], list[AgentEvent]]:
        deps = CommerceDependencies(executor, memory, self._analysis)
        if memory is not None:
            prompt = f"{prompt}\n\nSaved customer context:\n{memory.context()}"
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
        memory: SessionMemory | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Relay tool events and sanitized model text while the full agent graph executes."""
        events: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        deps = CommerceDependencies(executor, memory, self._analysis, event_sink=events.put_nowait)
        if memory is not None:
            prompt = f"{prompt}\n\nSaved customer context:\n{memory.context()}"
        redactor = StreamingRedactor()

        async def relay_model_events(_: RunContext[CommerceDependencies], stream: Any) -> None:
            async for event in stream:
                if (
                    isinstance(event, PartDeltaEvent)
                    and isinstance(event.delta, TextPartDelta)
                    and (text := redactor.feed(event.delta.content_delta))
                ):
                    events.put_nowait(AgentEvent.text_delta(text))

        async def run_agent() -> None:
            try:
                result = await self._agent.run(
                    prompt,
                    deps=deps,
                    message_history=message_history,
                    usage_limits=self._limits,
                    event_stream_handler=relay_model_events,
                )
            except AssertionError as error:
                if "stream_function" in str(error):
                    # FunctionModel supports non-streaming test doubles without a stream callback.
                    text, history, buffered_events = await self.run(
                        prompt, executor=executor, message_history=message_history, memory=memory
                    )
                    if message_history is not None:
                        message_history[:] = history
                    for event in buffered_events:
                        if event.type != "turn_complete":
                            events.put_nowait(event)
                    if text:
                        events.put_nowait(AgentEvent.text_delta(redactor.finish() + text))
                    events.put_nowait(
                        next(event for event in buffered_events if event.type == "turn_complete")
                    )
                else:
                    logger.exception("commerce agent stream failed")
                    events.put_nowait(
                        AgentEvent.error(
                            "The agent could not complete this turn. Please try again."
                        )
                    )
                    events.put_nowait(
                        AgentEvent.complete({"input_tokens": 0, "output_tokens": 0, "requests": 0})
                    )
            except Exception:
                logger.exception("commerce agent stream failed")
                events.put_nowait(
                    AgentEvent.error("The agent could not complete this turn. Please try again.")
                )
                events.put_nowait(
                    AgentEvent.complete({"input_tokens": 0, "output_tokens": 0, "requests": 0})
                )
            else:
                if message_history is not None:
                    message_history[:] = result.all_messages()
                if text := redactor.finish():
                    events.put_nowait(AgentEvent.text_delta(text))
                usage = result.usage
                events.put_nowait(
                    AgentEvent.complete(
                        {
                            "input_tokens": usage.input_tokens or 0,
                            "output_tokens": usage.output_tokens or 0,
                            "requests": usage.requests,
                        }
                    )
                )
            finally:
                events.put_nowait(None)

        task = asyncio.create_task(run_agent())
        try:
            while (event := await events.get()) is not None:
                yield event
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
