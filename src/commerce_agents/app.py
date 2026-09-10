"""Retail FastAPI host retaining the original SSE event vocabulary."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic_ai.messages import ModelMessage

from .events import AgentEvent
from .memory import SessionMemory
from .merchant import ChangeNotApplicable, MerchantExecutor
from .retail import RetailExecutor, Role, build_retail_agent
from .shopping import ShoppingExecutor
from .travel import TravelBackend


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)


@dataclass
class Session:
    executor: RetailExecutor = field(default_factory=RetailExecutor)
    shopping_executor: ShoppingExecutor | None = None
    merchant_executor: MerchantExecutor | None = None
    history: list[ModelMessage] = field(default_factory=list)
    memory: SessionMemory = field(default_factory=SessionMemory)


class RetailHost:
    def __init__(self, model: str) -> None:
        self._agents = {
            role: build_retail_agent(role, model) for role in ("shopping", "merchant", "travel")
        }
        self._sessions: dict[tuple[Role, str], Session] = {}

    def start(self, role: Role) -> str:
        session_id = uuid4().hex
        session = Session()
        if role == "shopping":
            session.shopping_executor = ShoppingExecutor(session.executor, session_id)
        elif role == "travel":
            session.shopping_executor = ShoppingExecutor(TravelBackend(), session_id)
        else:
            from .retail import CATALOG

            session.merchant_executor = MerchantExecutor(list(CATALOG))
        self._sessions[(role, session_id)] = session
        return session_id

    async def turn(self, role: Role, session_id: str, message: str) -> list[AgentEvent]:
        session = self._sessions.get((role, session_id))
        if session is None:
            raise KeyError(session_id)
        executor = (
            session.shopping_executor
            if role in {"shopping", "travel"}
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
            if role in {"shopping", "travel"}
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

    def approve_change(self, session_id: str, change_id: str) -> dict:
        session = self._sessions.get(("merchant", session_id))
        if session is None or session.merchant_executor is None:
            raise KeyError(session_id)
        return session.merchant_executor.approve(change_id).model_dump(mode="json")


def _sse(events: AsyncIterator[AgentEvent]) -> AsyncIterator[str]:
    async def frames() -> AsyncIterator[str]:
        async for event in events:
            yield f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"

    return frames()


def create_app(model: str | None = None) -> FastAPI:
    host = RetailHost(model or os.environ.get("COMMERCE_MODEL", "openai:gpt-5.2"))
    app = FastAPI(title="Retail Commerce Agents")
    app.state.retail_host = host

    def routes(role: Role, prefix: str) -> None:
        @app.post(f"{prefix}/session")
        async def start_session() -> dict[str, str]:
            return {"session_id": host.start(role)}

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

    routes("shopping", "/api")
    routes("travel", "/api/travel")
    routes("merchant", "/api/merchant")

    @app.post("/api/merchant/changes/{change_id}/approve")
    async def approve_change(
        change_id: str, x_session_id: str | None = Header(default=None)
    ) -> dict:
        if not x_session_id:
            raise HTTPException(status_code=401, detail="X-Session-Id is required")
        try:
            return {"change": host.approve_change(x_session_id, change_id)}
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Unknown session") from error
        except ChangeNotApplicable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app


app = create_app()
