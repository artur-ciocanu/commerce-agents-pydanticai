"""Provider-neutral console entry point for the retail reference agents."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import cast

from .retail import RetailExecutor, Role, build_retail_agent


async def chat(role: Role, model: str) -> None:
    agent = build_retail_agent(role, model)
    executor = RetailExecutor()
    history = []
    print(f"Retail {role} agent. Type 'exit' to quit.")
    while True:
        prompt = (await asyncio.to_thread(input, "> ")).strip()
        if prompt.lower() in {"exit", "quit", "q"}:
            return
        if not prompt:
            continue
        text, history, events = await agent.run(prompt, executor=executor, message_history=history)
        for event in events:
            if event.type in {"cart_update", "change_update"}:
                print(event.data)
        print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a retail commerce agent")
    parser.add_argument("role", choices=("shopping", "merchant"))
    parser.add_argument("--model", default=os.environ.get("COMMERCE_MODEL", "openai:gpt-5.2"))
    args = parser.parse_args()
    asyncio.run(chat(cast(Role, args.role), args.model))


if __name__ == "__main__":
    main()
