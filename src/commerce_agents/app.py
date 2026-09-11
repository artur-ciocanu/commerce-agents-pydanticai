"""Retail FastAPI host retaining the original SSE event vocabulary."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic_ai.messages import ModelMessage

from .events import AgentEvent
from .memory import SessionMemory
from .merchant import ChangeNotApplicable, MerchantExecutor
from .reference.adapter import (
    EntertainmentBackendAdapter,
    RetailBackendAdapter,
    TelecomBackendAdapter,
    TravelBackendAdapter,
)
from .reference.entertainment import MockTicketing
from .reference.merchant_entertainment import MockTicketingMerchant
from .reference.merchant_retail import MockRetailMerchant
from .reference.merchant_telecom import MockTelecomMerchant
from .reference.merchant_travel import MockTravelMerchant
from .reference.retail import MockRetail
from .reference.telecom import MockTelecom
from .reference.ticketing import NotFoundError, OwnershipError, StateError, TicketingError
from .reference.travel import MockTravel
from .retail import SHOPPING_SKILLS, RetailExecutor, Role, build_retail_agent
from .shopping import ShoppingExecutor
from .source_merchant import SourceMerchantExecutor


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)


class StartSessionRequest(BaseModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=64)


class CartAddRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=1, ge=1, le=10)


class IdentifierRequest(BaseModel):
    hold_id: str | None = Field(default=None, min_length=1, max_length=80)
    offer_id: str | None = Field(default=None, min_length=1, max_length=80)
    transfer_id: str | None = Field(default=None, min_length=1, max_length=80)


class WaitlistJoinRequest(CartAddRequest):
    quantity: int = Field(default=1, ge=1, le=8)


class TransferRequest(BaseModel):
    ticket_ids: list[str] = Field(min_length=1, max_length=4)
    recipient: str = Field(min_length=1, max_length=80)


class MemoryFactRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: str | None = Field(default=None, max_length=240)


class ResetRequest(BaseModel):
    clear_memory: bool = False
    purge_memory: bool = False


@dataclass
class Session:
    executor: RetailExecutor = field(default_factory=RetailExecutor)
    shopping_executor: ShoppingExecutor | None = None
    merchant_executor: Any | None = None
    history: list[ModelMessage] = field(default_factory=list)
    memory: SessionMemory = field(default_factory=SessionMemory)


class RetailHost:
    def __init__(self, model: str) -> None:
        self.model = model
        self._agents = {
            role: build_retail_agent(role, model)
            for role in (
                "shopping",
                "merchant",
                "retail_merchant",
                "travel",
                "telecom",
                "entertainment",
                "travel_merchant",
                "telecom_merchant",
                "entertainment_merchant",
            )
        }
        self._sessions: dict[tuple[Role, str], Session] = {}
        self._storefronts = {
            "retail": MockRetail(),
            "travel": MockTravel(),
            "telecom": MockTelecom(),
            "entertainment": MockTicketing(),
        }

    def start(self, role: Role, user_id: str = "demo-user") -> str:
        session_id = uuid4().hex
        session = Session()
        if role == "shopping":
            session.shopping_executor = ShoppingExecutor(
                RetailBackendAdapter(session_id, self._storefronts["retail"], user_id),
                session_id,
                skills=SHOPPING_SKILLS,
            )
        elif role == "travel":
            session.shopping_executor = ShoppingExecutor(
                TravelBackendAdapter(session_id, self._storefronts["travel"], user_id),
                session_id,
                skills=SHOPPING_SKILLS,
            )
        elif role == "telecom":
            session.shopping_executor = ShoppingExecutor(
                TelecomBackendAdapter(session_id, self._storefronts["telecom"], user_id),
                session_id,
                skills=SHOPPING_SKILLS,
            )
        elif role == "entertainment":
            session.shopping_executor = ShoppingExecutor(
                EntertainmentBackendAdapter(
                    session_id, self._storefronts["entertainment"], user_id
                ),
                session_id,
                skills=SHOPPING_SKILLS,
            )
        elif role == "merchant":
            from .retail import CATALOG

            session.merchant_executor = MerchantExecutor(list(CATALOG))
        elif role == "retail_merchant":
            session.merchant_executor = SourceMerchantExecutor(
                MockRetailMerchant(self._storefronts["retail"]), session_id, operator="Avery"
            )
        elif role == "travel_merchant":
            session.merchant_executor = SourceMerchantExecutor(
                MockTravelMerchant(self._storefronts["travel"]), session_id, operator="Marta"
            )
        elif role == "telecom_merchant":
            session.merchant_executor = SourceMerchantExecutor(
                MockTelecomMerchant(self._storefronts["telecom"]), session_id, operator="Sam"
            )
        else:
            session.merchant_executor = SourceMerchantExecutor(
                MockTicketingMerchant(self._storefronts["entertainment"]), session_id, operator="Jo"
            )
        self._sessions[(role, session_id)] = session
        return session_id

    async def turn(self, role: Role, session_id: str, message: str) -> list[AgentEvent]:
        session = self._sessions.get((role, session_id))
        if session is None:
            raise KeyError(session_id)
        executor = (
            session.shopping_executor
            if role in {"shopping", "travel", "telecom", "entertainment"}
            else session.merchant_executor
        )
        assert executor is not None
        _, session.history, events = await self._agents[role].run(
            message, executor=executor, message_history=session.history, memory=session.memory
        )
        return events

    def session(self, role: Role, session_id: str) -> Session:
        session = self._sessions.get((role, session_id))
        if session is None:
            raise KeyError(session_id)
        return session

    async def stream_turn(
        self, role: Role, session_id: str, message: str
    ) -> AsyncIterator[AgentEvent]:
        session = self.session(role, session_id)
        executor = (
            session.shopping_executor
            if role in {"shopping", "travel", "telecom", "entertainment"}
            else session.merchant_executor
        )
        assert executor is not None
        async for event in self._agents[role].stream_turn(
            message,
            executor=executor,
            message_history=session.history,
            memory=session.memory,
        ):
            yield event

    def approve_change(self, role: Role, session_id: str, change_id: str) -> dict:
        session = self._sessions.get((role, session_id))
        if session is None or session.merchant_executor is None:
            raise KeyError(session_id)
        return session.merchant_executor.approve(change_id).model_dump(mode="json")

    def reset(self, role: Role, session_id: str) -> str:
        session = self.session(role, session_id)
        if session.shopping_executor is not None:
            reset_session = getattr(
                session.shopping_executor.backend._backend, "reset_session", None
            )
            if reset_session is not None:
                reset_session(session_id)
        user_id = (
            getattr(session.shopping_executor.backend._session, "user_id", "demo-user")
            if session.shopping_executor
            else "demo-user"
        )
        del self._sessions[(role, session_id)]
        return self.start(role, user_id)


def _sse(events: AsyncIterator[AgentEvent]) -> AsyncIterator[str]:
    async def frames() -> AsyncIterator[str]:
        async for event in events:
            yield f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"

    return frames()


def create_app(model: str | None = None, *, vertical: str | None = None) -> FastAPI:
    if vertical not in {None, "retail", "travel", "telecom", "entertainment"}:
        raise ValueError(f"Unknown vertical: {vertical}")
    host = RetailHost(model or os.environ.get("COMMERCE_MODEL", "openai:gpt-5.2"))
    app = FastAPI(title=f"{(vertical or 'retail').title()} Commerce Agents")
    app.mount(
        "/products",
        StaticFiles(directory=Path(__file__).parent / "reference" / "product_images"),
        name="products",
    )
    app.state.retail_host = host

    def routes(role: Role, prefix: str) -> None:
        @app.post(f"{prefix}/session")
        async def start_session(
            request: StartSessionRequest | None = None,
        ) -> dict[str, str | None]:
            user_id = (request or StartSessionRequest()).user_id
            session_id = host.start(role, user_id)
            profile = None
            if role in {"shopping", "travel", "telecom", "entertainment"}:
                executor = host.session(role, session_id).shopping_executor
                assert executor is not None
                profile = await executor.backend.get_preferences()
            if role in {
                "retail_merchant",
                "travel_merchant",
                "telecom_merchant",
                "entertainment_merchant",
            }:
                merchant = host.session(role, session_id).merchant_executor
                assert isinstance(merchant, SourceMerchantExecutor)
                return {
                    "session_id": session_id,
                    "merchant_id": merchant.session.merchant_id,
                    "operator": merchant.session.operator,
                }
            return {
                "session_id": session_id,
                "user_id": user_id,
                "name": profile.get("display_name") if profile else None,
                "tier": profile.get("loyalty_tier") if profile else None,
            }

        @app.post(f"{prefix}/chat")
        async def chat(
            request: ChatRequest, x_session_id: str | None = Header(default=None)
        ) -> StreamingResponse:
            if not x_session_id:
                raise HTTPException(status_code=401, detail="X-Session-Id is required")
            try:
                host.session(role, x_session_id)
            except KeyError as error:
                raise HTTPException(status_code=404, detail="Unknown session") from error
            return StreamingResponse(
                _sse(host.stream_turn(role, x_session_id, request.message)),
                media_type="text/event-stream",
            )

    root_role: Role = {
        None: "shopping",
        "retail": "shopping",
        "travel": "travel",
        "telecom": "telecom",
        "entertainment": "entertainment",
    }[vertical]
    root_merchant_role: Role = {
        None: "merchant",
        "retail": "retail_merchant",
        "travel": "travel_merchant",
        "telecom": "telecom_merchant",
        "entertainment": "entertainment_merchant",
    }[vertical]

    routes(root_role, "/api")
    routes("travel", "/api/travel")
    routes("telecom", "/api/telecom")
    routes("entertainment", "/api/entertainment")
    routes(root_merchant_role, "/api/merchant")
    routes("retail_merchant", "/api/retail/merchant")
    routes("travel_merchant", "/api/travel/merchant")
    routes("telecom_merchant", "/api/telecom/merchant")
    routes("entertainment_merchant", "/api/entertainment/merchant")

    def shopping_session(role: Role, session_id: str | None) -> ShoppingExecutor:
        if not session_id:
            raise HTTPException(status_code=401, detail="X-Session-Id is required")
        try:
            executor = host.session(role, session_id).shopping_executor
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Unknown session") from error
        if executor is None:
            raise HTTPException(status_code=404, detail="Unknown session")
        return executor

    def executor_session(role: Role, session_id: str | None) -> Session:
        if not session_id:
            raise HTTPException(status_code=401, detail="X-Session-Id is required")
        try:
            return host.session(role, session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Unknown session") from error

    def cart_payload(cart: Any) -> dict[str, Any]:
        return {
            "items": [
                item.model_dump(mode="json") | {"line_total": round(item.price * item.quantity, 2)}
                for item in cart.items
            ],
            "item_count": sum(item.quantity for item in cart.items),
            "subtotal": cart.subtotal,
            "currency": cart.currency,
        }

    def ticket_error(error: TicketingError) -> HTTPException:
        if isinstance(error, OwnershipError):
            status_code = 403
        elif isinstance(error, NotFoundError):
            status_code = 404
        elif isinstance(error, StateError):
            status_code = 409
        else:
            status_code = 400
        return HTTPException(status_code=status_code, detail=str(error))

    def storefront_routes(role: Role, prefix: str, kind: str) -> None:
        @app.get(f"{prefix}/products")
        async def list_products(
            category: str | None = None, limit: int = Query(default=24, ge=1, le=100)
        ) -> dict[str, list[dict[str, Any]]]:
            backend = host._storefronts[kind]
            products = [
                product
                for product in backend.products.values()
                if not category or product.category == category
            ]
            return {
                "products": [
                    product.model_dump(
                        exclude={"long_description", "specs", "review_highlights", "variants"}
                    )
                    for product in products[:limit]
                ]
            }

        @app.get(f"{prefix}/products/{{product_id:path}}")
        async def get_product(product_id: str) -> dict[str, Any]:
            backend = host._storefronts[kind]
            product = backend.product(product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            payload = product.model_dump(mode="json")
            if kind == "retail":
                payload |= {
                    "price_intelligence": backend.price_intelligence(product_id),
                    "review_aspects": backend.review_aspects(product_id),
                }
            return payload

        @app.get(f"{prefix}/cart")
        async def get_cart(x_session_id: str | None = Header(default=None)) -> dict[str, Any]:
            executor = shopping_session(role, x_session_id)
            return cart_payload(await executor.backend.get_cart(executor.session_id))

        @app.get(f"{prefix}/orders")
        async def get_orders(x_session_id: str | None = Header(default=None)) -> dict[str, Any]:
            executor = shopping_session(role, x_session_id)
            return {"orders": await executor.backend.get_orders(20)}

        @app.get(f"{prefix}/memory")
        async def get_memory(x_session_id: str | None = Header(default=None)) -> dict[str, Any]:
            session = executor_session(role, x_session_id)
            return {
                "facts": [
                    {"key": key, "value": value} for key, value in session.memory.facts.items()
                ]
            }

        @app.patch(f"{prefix}/memory")
        async def edit_memory(
            request: MemoryFactRequest, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            session = executor_session(role, x_session_id)
            if request.key not in session.memory.facts:
                raise HTTPException(status_code=404, detail="No such fact")
            if request.value is None:
                raise HTTPException(status_code=400, detail="Value must not be empty")
            try:
                key = session.memory.save(request.key, request.value)
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            return {"ok": True, "fact": {"key": key, "value": session.memory.facts[key]}}

        @app.delete(f"{prefix}/memory")
        async def delete_memory(
            request: MemoryFactRequest, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            session = executor_session(role, x_session_id)
            if request.key not in session.memory.facts:
                raise HTTPException(status_code=404, detail="No such fact")
            del session.memory.facts[request.key]
            return {"ok": True, "deleted": request.key}

        @app.post(f"{prefix}/reset")
        async def reset(
            request: ResetRequest, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            session = executor_session(role, x_session_id)
            if request.clear_memory or request.purge_memory:
                session.memory.facts.clear()
            return {"ok": True, "session_id": host.reset(role, x_session_id or "")}

        @app.get(f"{prefix}/health")
        async def health() -> dict[str, Any]:
            backend = host._storefronts[kind]
            return {
                "ok": True,
                "store": backend.store_name,
                "products": len(backend.products),
                "skills": SHOPPING_SKILLS.names,
                "model": host.model,
            }

        if kind in {"retail", "telecom", "entertainment"}:

            @app.post(f"{prefix}/cart/add")
            async def add_to_cart(
                request: CartAddRequest, x_session_id: str | None = Header(default=None)
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                backend = executor.backend._backend
                product = backend.product(request.product_id)
                if product is None:
                    raise HTTPException(status_code=404, detail="Product not found")
                if kind == "telecom" and product.category not in {"devices", "add-ons"}:
                    raise HTTPException(
                        status_code=400,
                        detail="Only devices and add-ons can be added directly. Plan and home-internet changes go through the ACME Assistant so the terms can be reviewed first.",
                    )
                if product.has_options:
                    raise HTTPException(
                        status_code=400,
                        detail="Choose the product's options with the assistant before adding it.",
                    )
                # A catalog detail is an authenticated host read, so record it through the
                # executor's provenance state before the same executor performs the write.
                detail = await executor.execute(
                    "get_product_details", {"product_id": request.product_id}
                )
                if detail.is_error:
                    raise HTTPException(status_code=404, detail="Product not found")
                try:
                    outcome = await executor.execute(
                        "add_to_cart",
                        {"product_id": request.product_id, "quantity": request.quantity},
                    )
                except TicketingError as error:
                    raise ticket_error(error) from error
                if outcome.blocked or outcome.is_error:
                    raise HTTPException(status_code=400, detail=outcome.result_text)
                cart = await executor.backend.get_cart(executor.session_id)
                return {"ok": True, "cart": cart_payload(cart)}

        if kind == "telecom":

            @app.get(f"{prefix}/account")
            async def get_account(
                x_session_id: str | None = Header(default=None),
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                return {"account": await executor.backend.get_account_context()}

        if kind == "entertainment":

            def ticketing(executor: ShoppingExecutor) -> MockTicketing:
                return executor.backend._backend

            def holds_payload(executor: ShoppingExecutor) -> dict[str, Any]:
                engine = ticketing(executor).engine
                return {
                    "hold_minutes": 8,
                    "offer_window_minutes": 10,
                    "holds": [
                        {
                            "hold_id": hold.hold_id,
                            "product_id": hold.product_id,
                            "quantity": hold.quantity,
                            "expires_at": hold.expires_at.isoformat(),
                            "seconds_remaining": engine.seconds_until(hold.expires_at),
                        }
                        for hold in engine.holds_for_session(executor.session_id)
                    ],
                }

            @app.get(f"{prefix}/holds")
            async def get_holds(x_session_id: str | None = Header(default=None)) -> dict[str, Any]:
                return holds_payload(shopping_session(role, x_session_id))

            @app.post(f"{prefix}/holds/release")
            async def release_hold(
                request: IdentifierRequest, x_session_id: str | None = Header(default=None)
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                try:
                    ticketing(executor).engine.release_hold_by_id(
                        request.hold_id or "", executor.backend._session.user_id
                    )
                except TicketingError as error:
                    raise ticket_error(error) from error
                return {"ok": True, **holds_payload(executor)}

            @app.post(f"{prefix}/waitlist/join")
            async def join_waitlist(
                request: WaitlistJoinRequest, x_session_id: str | None = Header(default=None)
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                if request.product_id not in executor.state.seen_products:
                    raise HTTPException(
                        status_code=400,
                        detail="That tier isn't in this session's results; search for the event first.",
                    )
                try:
                    position = ticketing(executor).engine.join_waitlist(
                        executor.backend._session.user_id,
                        executor.session_id,
                        request.product_id,
                        request.quantity,
                    )
                except TicketingError as error:
                    raise ticket_error(error) from error
                return {"ok": True, "position": position}

            @app.get(f"{prefix}/waitlist")
            async def get_waitlist(
                x_session_id: str | None = Header(default=None),
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                engine, user_id = ticketing(executor).engine, executor.backend._session.user_id
                return {
                    "entries": [
                        {
                            "product_id": entry.product_id,
                            "quantity": entry.quantity,
                            "position": position,
                        }
                        for entry, position in engine.waitlist_entries_for(user_id)
                    ],
                    "offers": [
                        {
                            "offer_id": offer.offer_id,
                            "product_id": offer.product_id,
                            "quantity": offer.quantity,
                            "expires_at": offer.expires_at.isoformat(),
                            "seconds_remaining": engine.seconds_until(offer.expires_at),
                        }
                        for offer in engine.offers_for(user_id)
                    ],
                }

            @app.post(f"{prefix}/waitlist/claim")
            async def claim_offer(
                request: IdentifierRequest, x_session_id: str | None = Header(default=None)
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                try:
                    hold = ticketing(executor).engine.claim_offer(
                        request.offer_id or "",
                        executor.backend._session.user_id,
                        executor.session_id,
                    )
                except TicketingError as error:
                    raise ticket_error(error) from error
                product = ticketing(executor).get_live_product(hold.product_id)
                if product:
                    executor.state.remember_products([product])
                return {"ok": True, **holds_payload(executor)}

            @app.post(f"{prefix}/demo/return")
            async def demo_return(request: WaitlistJoinRequest) -> dict[str, Any]:
                backend = host._storefronts["entertainment"]
                if request.product_id not in backend.products:
                    raise HTTPException(status_code=404, detail="Product not found")
                try:
                    backend.engine.record_return(request.product_id, request.quantity)
                except TicketingError as error:
                    raise ticket_error(error) from error
                return {"ok": True, "remaining": backend.engine.remaining(request.product_id)}

            @app.get(f"{prefix}/tickets")
            async def get_tickets(
                x_session_id: str | None = Header(default=None),
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                backend, user_id = ticketing(executor), executor.backend._session.user_id
                return {
                    "tickets": [
                        {
                            "ticket_id": ticket.ticket_id,
                            "event": backend.products[ticket.product_id].attributes.get(
                                "event_name", ticket.product_id
                            ),
                            "date": backend.products[ticket.product_id].attributes.get(
                                "event_date"
                            ),
                            "venue": backend.products[ticket.product_id].attributes.get("venue"),
                            "tier": backend.products[ticket.product_id].attributes.get("tier"),
                            "seat": ticket.seat,
                            "status": ticket.status,
                            "entry_code": backend.engine.barcode(ticket.ticket_id),
                            "entry_code_rotates_s": 60,
                        }
                        for ticket in backend.engine.tickets_for(user_id)
                    ]
                }

            @app.post(f"{prefix}/tickets/transfer")
            async def transfer_tickets(
                request: TransferRequest, x_session_id: str | None = Header(default=None)
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                try:
                    transfer = ticketing(executor).engine.initiate_transfer(
                        executor.backend._session.user_id,
                        request.ticket_ids,
                        request.recipient.strip(),
                    )
                except TicketingError as error:
                    raise ticket_error(error) from error
                return {
                    "ok": True,
                    "transfer": {
                        "transfer_id": transfer.transfer_id,
                        "ticket_ids": transfer.ticket_ids,
                        "recipient": transfer.recipient,
                        "status": transfer.status,
                    },
                }

            @app.post(f"{prefix}/tickets/transfer/cancel")
            async def cancel_transfer(
                request: IdentifierRequest, x_session_id: str | None = Header(default=None)
            ) -> dict[str, Any]:
                executor = shopping_session(role, x_session_id)
                try:
                    transfer = ticketing(executor).engine.cancel_transfer(
                        executor.backend._session.user_id, request.transfer_id or ""
                    )
                except TicketingError as error:
                    raise ticket_error(error) from error
                return {"ok": True, "status": transfer.status}

    storefront_routes(root_role, "/api", "retail" if vertical is None else vertical)
    storefront_routes("travel", "/api/travel", "travel")
    storefront_routes("telecom", "/api/telecom", "telecom")
    storefront_routes("entertainment", "/api/entertainment", "entertainment")

    @app.post("/api/merchant/changes/{change_id}/approve")
    async def approve_change(
        change_id: str, x_session_id: str | None = Header(default=None)
    ) -> dict:
        if not x_session_id:
            raise HTTPException(status_code=401, detail="X-Session-Id is required")
        try:
            return {"change": host.approve_change(root_merchant_role, x_session_id, change_id)}
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Unknown session") from error
        except ChangeNotApplicable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def approval_route(role: Role, prefix: str) -> None:
        @app.post(f"{prefix}/changes/{{change_id}}/approve")
        async def approve_vertical_change(
            change_id: str, x_session_id: str | None = Header(default=None)
        ) -> dict:
            if not x_session_id:
                raise HTTPException(status_code=401, detail="X-Session-Id is required")
            try:
                return {"change": host.approve_change(role, x_session_id, change_id)}
            except KeyError as error:
                raise HTTPException(status_code=404, detail="Unknown session") from error
            except ChangeNotApplicable as error:
                raise HTTPException(status_code=409, detail=str(error)) from error

    def merchant_session(role: Role, session_id: str | None) -> SourceMerchantExecutor:
        session = executor_session(role, session_id)
        executor = session.merchant_executor
        if not isinstance(executor, SourceMerchantExecutor):
            raise HTTPException(status_code=404, detail="Unknown session")
        return executor

    def merchant_routes(role: Role, prefix: str, kind: str) -> None:
        @app.get(f"{prefix}/overview")
        async def overview(x_session_id: str | None = Header(default=None)) -> dict[str, Any]:
            executor = merchant_session(role, x_session_id)
            backend, context = executor.backend, executor.session
            snapshot, alerts, issues, pending = (
                await backend.get_business_snapshot(context),
                await backend.get_inventory_alerts(context),
                await backend.get_order_issues(context),
                await backend.get_pending_changes(context),
            )
            resolved = sorted(
                backend.ledger.resolved(),
                key=lambda change: change.applied_at or change.discarded_at or change.created_at,
                reverse=True,
            )
            extras: dict[str, Any] = {}
            if kind == "retail":
                extras = {
                    "trends": backend.kpi_trends(),
                    "trends_prior": backend.kpi_trends(periods_back=1),
                    "insights": backend.home_insights(),
                }
            elif kind in {"travel", "telecom", "entertainment"}:
                extras = {"today": backend.today_snapshot()}
            return {
                "snapshot": snapshot.model_dump(mode="json", exclude_none=True),
                "needs_attention": {
                    "inventory": [
                        item.model_dump(mode="json", exclude_none=True) for item in alerts[:6]
                    ],
                    "order_issues": [
                        item.model_dump(mode="json", exclude_none=True) for item in issues[:6]
                    ],
                    "pending_changes": [
                        item.model_dump(mode="json", exclude_none=True) for item in pending[:6]
                    ],
                },
                "recent_orders": [
                    {
                        "order_id": order.order_id,
                        "status": order.status.value,
                        "placed_at": order.placed_at.isoformat(),
                        "total": order.total,
                        "items": sum(item.quantity for item in order.items),
                    }
                    for order in host._storefronts[kind].recent_orders(6)
                ],
                "recent_changes": [
                    item.model_dump(mode="json", exclude_none=True) for item in resolved[:8]
                ],
                **extras,
            }

        @app.get(f"{prefix}/listings")
        async def listings(
            query: str | None = None,
            limit: int = Query(default=100, ge=1, le=100),
            x_session_id: str | None = Header(default=None),
        ) -> dict[str, Any]:
            executor = merchant_session(role, x_session_id)
            backend = executor.backend
            results = (
                await backend.search_listings(executor.session, query, None, 100)
                if query
                else backend.all_listings()
            )
            return {
                "total": len(results),
                "listings": [
                    item.model_dump(mode="json", exclude_none=True) for item in results[:limit]
                ],
            }

        @app.get(f"{prefix}/listings/{{listing_id:path}}")
        async def listing_detail(
            listing_id: str, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            executor = merchant_session(role, x_session_id)
            listing = await executor.backend.get_listing(executor.session, listing_id)
            if listing is None:
                raise HTTPException(status_code=404, detail="Listing not found")
            pricing = await executor.backend.get_pricing_context(
                executor.session, listing.listing_id
            )
            return {
                "listing": listing.model_dump(mode="json", exclude_none=True),
                "pricing": pricing.model_dump(mode="json", exclude_none=True) if pricing else None,
            }

        @app.get(f"{prefix}/alerts")
        async def alerts(x_session_id: str | None = Header(default=None)) -> dict[str, Any]:
            executor = merchant_session(role, x_session_id)
            backend, context = executor.backend, executor.session
            return {
                "inventory": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in await backend.get_inventory_alerts(context)
                ],
                "order_issues": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in await backend.get_order_issues(context)
                ],
            }

        async def portal_read(x_session_id: str | None = Header(default=None)) -> dict[str, Any]:
            backend = merchant_session(role, x_session_id).backend
            if kind == "travel":
                return await backend.occupancy_overview()
            if kind == "telecom":
                return backend.base_overview()
            return backend.pacing_overview()

        if kind == "travel":
            app.add_api_route(f"{prefix}/occupancy", portal_read, methods=["GET"])
        elif kind == "telecom":
            app.add_api_route(f"{prefix}/base", portal_read, methods=["GET"])
        elif kind == "entertainment":
            app.add_api_route(f"{prefix}/pacing", portal_read, methods=["GET"])

        @app.post(f"{prefix}/changes/{{change_id:path}}/apply")
        async def apply_change(
            change_id: str, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            try:
                ok, change, reason = await merchant_session(role, x_session_id).change_action(
                    change_id, "apply_change"
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            return {"ok": ok, "change": change, **({"reason": reason} if not ok else {})}

        @app.post(f"{prefix}/changes/{{change_id:path}}/discard")
        async def discard_change(
            change_id: str, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            try:
                ok, change, reason = await merchant_session(role, x_session_id).change_action(
                    change_id, "discard_change"
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            return {"ok": ok, "change": change, **({"reason": reason} if not ok else {})}

        @app.get(f"{prefix}/memory")
        async def get_merchant_memory(
            x_session_id: str | None = Header(default=None),
        ) -> dict[str, Any]:
            return {
                "facts": [
                    {"key": key, "value": value}
                    for key, value in executor_session(role, x_session_id).memory.facts.items()
                ]
            }

        @app.delete(f"{prefix}/memory")
        async def delete_merchant_memory(
            request: MemoryFactRequest, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            memory = executor_session(role, x_session_id).memory.facts
            if request.key not in memory:
                raise HTTPException(status_code=404, detail="No such fact")
            del memory[request.key]
            return {"ok": True, "deleted": request.key}

        @app.post(f"{prefix}/reset")
        async def reset_merchant(
            request: ResetRequest, x_session_id: str | None = Header(default=None)
        ) -> dict[str, Any]:
            session = executor_session(role, x_session_id)
            if request.purge_memory:
                session.memory.facts.clear()
            return {"ok": True, "session_id": host.reset(role, x_session_id or "")}

        @app.get(f"{prefix}/health")
        async def merchant_health() -> dict[str, Any]:
            return {
                "ok": True,
                "store": host._storefronts[kind].store_name,
                "role": "merchant",
                "listings": len(host._storefronts[kind].products),
                "skills": [],
                "model": host.model,
            }

    approval_route("retail_merchant", "/api/retail/merchant")
    approval_route("travel_merchant", "/api/travel/merchant")
    approval_route("telecom_merchant", "/api/telecom/merchant")
    approval_route("entertainment_merchant", "/api/entertainment/merchant")

    if vertical is not None:
        merchant_routes(root_merchant_role, "/api/merchant", vertical)
    merchant_routes("retail_merchant", "/api/retail/merchant", "retail")
    merchant_routes("travel_merchant", "/api/travel/merchant", "travel")
    merchant_routes("telecom_merchant", "/api/telecom/merchant", "telecom")
    merchant_routes("entertainment_merchant", "/api/entertainment/merchant", "entertainment")

    return app


app = create_app()
