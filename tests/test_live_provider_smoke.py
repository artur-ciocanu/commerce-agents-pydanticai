"""Opt-in provider smoke coverage; never runs without an explicit model selection."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from commerce_agents.app import create_app


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("COMMERCE_MODEL"), reason="COMMERCE_MODEL is not configured")
def test_live_provider_streams_tools_history_and_sse() -> None:
    app = create_app(os.environ["COMMERCE_MODEL"])
    with TestClient(app) as client:
        session_id = client.post("/api/session").json()["session_id"]
        response = client.post(
            "/api/chat",
            headers={"X-Session-Id": session_id},
            json={"message": "Find an in-stock camping item and show its details."},
        )
        history = app.state.retail_host.session("shopping", session_id).history

    assert response.status_code == 200
    assert "event: tool_call" in response.text
    assert "event: turn_complete" in response.text
    assert history
