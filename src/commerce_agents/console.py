"""Provider-neutral console entry point for the retail reference agents."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import cast

from .memory import SessionMemory
from .merchant import MerchantExecutor
from .retail import CATALOG, RetailExecutor, Role, build_retail_agent
from .runtime import CommerceAgent, ToolExecutor
from .shopping import ShoppingExecutor
from .travel import TravelBackend


async def _stream(
    agent: CommerceAgent,
    prompt: str,
    executor: ToolExecutor,
    history: list,
    memory: SessionMemory,
) -> list[str]:
    staged: list[str] = []
    wrote_text = False
    async for event in agent.stream_turn(
        prompt, executor=executor, message_history=history, memory=memory
    ):
        if event.type == "text_delta":
            print(event.data["text"], end="", flush=True)
            wrote_text = True
        elif event.type == "tool_result" and event.data["status"] != "ok":
            print(f"\n[{event.data['tool']}: {event.data['summary']}]")
        elif event.type in {"cart_update", "change_update"}:
            print(f"\n{event.data}")
            if event.type == "change_update" and event.data["change"]["status"] == "staged":
                staged.append(event.data["change"]["change_id"])
        elif event.type == "error":
            print(f"\n[error: {event.data['message']}]")
    if wrote_text:
        print()
    return staged


async def chat(role: Role, model: str) -> None:
    agent = build_retail_agent(role, model)
    executor: ToolExecutor
    if role == "shopping":
        executor = ShoppingExecutor(RetailExecutor(), "console")
    elif role == "travel":
        executor = ShoppingExecutor(TravelBackend(), "console")
    else:
        executor = MerchantExecutor(list(CATALOG), operator="console-operator")
    history = []
    memory = SessionMemory()
    print(f"Retail {role} agent. Type 'exit' to quit.")
    while True:
        prompt = (await asyncio.to_thread(input, "> ")).strip()
        if prompt.lower() in {"exit", "quit", "q"}:
            return
        if not prompt:
            continue
        staged = await _stream(agent, prompt, executor, history, memory)
        if role != "merchant":
            continue
        merchant = cast(MerchantExecutor, executor)
        for change_id in staged:
            approved = (
                (await asyncio.to_thread(input, f"Approve {change_id}? [y/N] ")).strip().lower()
            )
            if approved not in {"y", "yes"}:
                print(f"{change_id} remains staged.")
                continue
            merchant.approve(change_id)
            await _stream(
                agent,
                f"The host approved {change_id}. Apply it now.",
                executor,
                history,
                memory,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a retail commerce agent")
    parser.add_argument("role", choices=("shopping", "merchant", "travel"))
    parser.add_argument("--model", default=os.environ.get("COMMERCE_MODEL", "openai:gpt-5.2"))
    args = parser.parse_args()
    asyncio.run(chat(cast(Role, args.role), args.model))


if __name__ == "__main__":
    main()
