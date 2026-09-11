# Commerce Agents for PydanticAI

This is a standalone, provider-agnostic PydanticAI migration of
[Anthropic's commerce-agents](https://github.com/anthropics/commerce-agents). It ports the
source domain contracts, fixtures, storefront and merchant backends, skills, guardrails, and
HTTP interfaces while replacing the Anthropic/Claude runtime orchestration with PydanticAI.

Migrated verticals: retail, travel, telecom, and entertainment. Source-backed merchant
runtimes and vendored `SKILL.md` files are included in this repository; it does not depend on
the original checkout at runtime.

## Install and Run

```bash
python -m pip install -e '.[dev]'
export COMMERCE_MODEL='openai:gpt-5.2'
python -m commerce_agents
```

`COMMERCE_MODEL` accepts normal PydanticAI model strings, for example:

```bash
export COMMERCE_MODEL='openai:gpt-5.2'
export COMMERCE_MODEL='anthropic:claude-sonnet-4-5'
export COMMERCE_MODEL='google-gla:gemini-3-flash-preview'
```

Configure credentials for the selected provider, such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
or `GEMINI_API_KEY`.

## HTTP APIs

`create_app()` runs the retail storefront at `/api` and retains the legacy simplified merchant
runtime at `/api/merchant`. It also exposes namespaced vertical routes:

| Vertical | Storefront | Source-backed merchant |
| --- | --- | --- |
| Retail | `/api` | `/api/retail/merchant` |
| Travel | `/api/travel` | `/api/travel/merchant` |
| Telecom | `/api/telecom` | `/api/telecom/merchant` |
| Entertainment | `/api/entertainment` | `/api/entertainment/merchant` |

For source-compatible single-vertical deployments, call `create_app(vertical="retail")`,
`create_app(vertical="travel")`, `create_app(vertical="telecom")`, or
`create_app(vertical="entertainment")`. In those apps, the selected storefront and its
source-backed merchant runtime are mounted at `/api` and `/api/merchant` respectively.

All storefronts provide `POST /session`, `POST /chat`, `GET /products`,
`GET /products/{product_id}`, `GET /cart`, and `GET /orders` below their prefix. Retail adds
`POST /cart/add` and detail-panel price/review enrichment. Telecom adds `POST /cart/add` for
devices and add-ons only, plus `GET /account`. Entertainment adds `POST /cart/add`,
`GET /holds`, `POST /holds/release`, `POST /waitlist/join`, `GET /waitlist`,
`POST /waitlist/claim`, `POST /demo/return`, `GET /tickets`,
`POST /tickets/transfer`, and `POST /tickets/transfer/cancel`.

Sessions are created with `POST .../session` and supplied through `X-Session-Id`. Catalog reads
are public; cart, account, ticket, agent, and approval operations require the header.

## Runtime Safety

The model receives JSON Schema tool contracts, not direct backend access. The application owns
tool execution, schema validation, bounded request/tool budgets, catalog provenance and variant
gates, output fencing, guardrails, filtered session memory, and host approvals.

`POST .../chat` streams server-sent events using `text_delta`, `tool_call`, `tool_result`,
`cart_update`, `change_update`, presentation `ui`, `error`, and `turn_complete` events.
Merchant changes remain staged until the host calls
`POST .../merchant/changes/{change_id}/approve`; approval is consumed when the matching change
is applied.

## Verification

The deterministic tests use `FunctionModel` and vendored fixtures. The live-provider smoke test
is opt-in:

```bash
mise exec -- uv run pytest -m live tests/test_live_provider_smoke.py
```

## Scope

This migration explicitly excludes the Claude Agent SDK, MCP deployment, and Managed Agents.
