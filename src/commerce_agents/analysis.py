"""Read-only merchant analysis delegated to a bounded specialist agent."""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, UsageLimits

from .events import ToolOutcome
from .fencing import Fence
from .guardrails import commerce_guardrails
from .runtime import ToolExecutor

ANALYSIS_FENCE = Fence("analysis_data")


class MerchantAnalysis:
    """A tool-less subagent that can reason over one host-fetched business snapshot."""

    def __init__(self, model: str) -> None:
        self._agent = Agent(
            model,
            instructions=(
                "You are a retail data analyst. Answer only from the fenced business snapshot. "
                "State when the snapshot cannot support a conclusion. You cannot make changes or "
                "request additional data."
            ),
            capabilities=commerce_guardrails(),
        )

    async def run(self, executor: ToolExecutor, arguments: dict[str, Any]) -> ToolOutcome:
        snapshot = await executor.execute("get_business_snapshot", {})
        if snapshot.is_error:
            return ToolOutcome(
                "Business data is temporarily unavailable for analysis.", is_error=True
            )
        question = ANALYSIS_FENCE.sanitize_text(arguments.get("question"), 300)
        prompt = (
            f"Question:\n{question}\n\n"
            f"Business snapshot:\n{snapshot.result_text}\n\n"
            "Give a concise, evidence-based answer."
        )
        try:
            result = await self._agent.run(prompt, usage_limits=UsageLimits(request_limit=1))
        except Exception:  # noqa: BLE001 - analysis is advisory and must not fail the parent turn.
            return ToolOutcome("Analysis is temporarily unavailable.", is_error=True)
        return ToolOutcome(str(result.output)[:1_500])
