# Commerce Agents for PydanticAI

Provider-agnostic shopping and merchant agent runtime built on PydanticAI v2.

## Live Provider Smoke Test

The deterministic suite does not require provider credentials. To exercise a configured
provider's streaming, tool selection, session history, and SSE relay, set `COMMERCE_MODEL`
and the matching provider credentials, then run:

```bash
mise exec -- uv run pytest -m live tests/test_live_provider_smoke.py
```

The runtime accepts a normal PydanticAI model specification, such as
`openai:gpt-5.2`, `anthropic:claude-sonnet-4-5`, or `google-gla:gemini-3-flash-preview`.
Commerce tool contracts remain JSON Schema documents and every tool call is delegated to the
application-owned executor. The model never receives direct backend access.

Every contract is validated again at execution time. Invalid model arguments trigger a PydanticAI
retry rather than reaching the backend; bounded request and tool-call budgets prevent runaway turns.
The shopping path additionally fences all backend data, loads skills from application-owned
`SKILL.md` files, and requires catalog provenance before it permits cart writes.

## Status

This repository is the in-progress PydanticAI port of Anthropic's commerce-agents reference.
The first milestone is the retail shopping and merchant API path. Managed Agents and Claude Code
SDK-specific skills are intentionally not part of this runtime.

## Install

```bash
python -m pip install -e '.[dev]'
```

Configure the selected provider with its normal environment variable, for example
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`.

## Run Retail

```bash
export COMMERCE_MODEL='openai:gpt-5.2'
python -m commerce_agents
```

Start a shopping session at `POST /api/session` and send `POST /api/chat` with its
`X-Session-Id` header. Merchant sessions use `/api/merchant/session` and
`/api/merchant/chat`. Both streams use `text_delta`, `tool_call`, `tool_result`,
`cart_update`, `change_update`, and `turn_complete` SSE events.

Merchant price changes are staged by the agent and guarded to a 20% movement. A host must approve
the staged `change_id` through `POST /api/merchant/changes/{change_id}/approve` before an
`apply_change` tool call can apply it; each approval is consumed after one use.

Travel sessions use `POST /api/travel/session` and `POST /api/travel/chat`. They use the same
provenance-gated cart flow, with travel-specific catalog data, booking terms, and policies.

For a terminal conversation, run `python -m commerce_agents.console shopping`,
`python -m commerce_agents.console travel`, or `python -m commerce_agents.console merchant`.
