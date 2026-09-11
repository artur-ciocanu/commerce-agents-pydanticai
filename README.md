# Commerce Agents for PydanticAI

A standalone, provider-agnostic PydanticAI migration of
[Anthropic's commerce-agents](https://github.com/anthropics/commerce-agents).
It includes migrated domain contracts, fixtures, storefronts, merchant portals,
skills, and HTTP interfaces for retail, travel, telecom, and entertainment.
It replaces the Claude runtime orchestration; it does not require the source
checkout at runtime.

## Quick Start

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
export COMMERCE_MODEL='openai:gpt-5.6-luna'
export OPENAI_API_KEY='...'
.venv/bin/python -m commerce_agents
```

`COMMERCE_MODEL` is a PydanticAI model string. Configure the matching provider
credential before starting the application.

| Model example | Required environment variable |
| --- | --- |
| `openai:gpt-5.6-luna` | `OPENAI_API_KEY` |
| `anthropic:claude-sonnet-4-5` | `ANTHROPIC_API_KEY` |
| `google-gla:gemini-3-flash-preview` | `GEMINI_API_KEY` |

The default model is `openai:gpt-5.2` when `COMMERCE_MODEL` is unset.

## Routes

`create_app()` uses retail at the root storefront prefix and keeps the original
simplified merchant agent at the root merchant prefix. It also mounts every
vertical under a namespace:

| Vertical | Storefront | Source-backed merchant portal |
| --- | --- | --- |
| Retail | `/api` | `/api/retail/merchant` |
| Travel | `/api/travel` | `/api/travel/merchant` |
| Telecom | `/api/telecom` | `/api/telecom/merchant` |
| Entertainment | `/api/entertainment` | `/api/entertainment/merchant` |

In the default app, `/api/merchant` is the simplified merchant runtime. For a
source-compatible root alias, use `create_app(vertical="retail")`,
`create_app(vertical="travel")`, `create_app(vertical="telecom")`, or
`create_app(vertical="entertainment")`. The selected storefront and its
source-backed merchant portal are then available at `/api` and `/api/merchant`.
The namespaced routes remain mounted.

All storefront prefixes expose `POST /session`, `POST /chat`, `GET /products`,
`GET /products/{product_id}`, `GET /cart`, `GET /orders`, and
`GET/PATCH/DELETE /memory`, plus `POST /reset` and `GET /health`. Retail,
telecom, and entertainment also expose `POST /cart/add`; telecom adds
`GET /account`. Entertainment adds
`GET /holds`, `POST /holds/release`, `POST /waitlist/join`, `GET /waitlist`,
`POST /waitlist/claim`, `POST /demo/return`, `GET /tickets`,
`POST /tickets/transfer`, and `POST /tickets/transfer/cancel`.

Merchant portals expose `POST /session`, `POST /chat`, `GET /overview`,
`GET /listings`, `GET /listings/{id}`, `GET /alerts`, staged-change
`POST /changes/{id}/approve`, `POST /changes/{id}/apply`, and
`POST /changes/{id}/discard`, plus memory, reset, and health endpoints. Travel,
telecom, and entertainment also expose `/occupancy`, `/base`, and `/pacing`,
respectively.

Create a session with `POST .../session` and send its ID as `X-Session-Id` for
session-scoped operations. Catalog reads and health checks are public; cart,
account, ticket, agent, memory, approval, and merchant portal operations use
the header. Retail product images are static assets at `/products/{filename}`.

`POST .../chat` returns `text/event-stream` SSE events: `text_delta`,
`tool_call`, `tool_result`, `cart_update`, `change_update`, presentation `ui`,
`error`, and `turn_complete`.

Entertainment ticketing maps ownership errors to `403`, missing records to
`404`, invalid state to `409`, and other ticketing errors to `400`.

## Safety Boundaries

The model receives JSON Schema tool contracts, not backend access. The
application executes tools and validates inputs, applies request and tool-call
limits, enforces catalog provenance and variant gates, fences model-facing
content, runs input/tool-result/output guardrails, filters session memory, and
requires host approval before staged merchant changes can be applied.

## Tests

The deterministic suite uses `FunctionModel` test doubles and vendored fixtures:

```bash
.venv/bin/pytest
```

The live-provider smoke test is opt-in and requires a configured provider key:

```bash
COMMERCE_MODEL="openai:gpt-5.6-luna" .venv/bin/pytest -m live tests/test_live_provider_smoke.py
```

## Scope

This migration does not include the Claude Agent SDK, MCP deployment, or
Managed Agents.
