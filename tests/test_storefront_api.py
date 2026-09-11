from __future__ import annotations

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from commerce_agents.app import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app("test")
    model = FunctionModel(lambda _messages, _info: ModelResponse(parts=[TextPart("ok")]))
    with ExitStack() as stack:
        for agent in app.state.retail_host._agents.values():
            stack.enter_context(agent._agent.override(model=model))
        with TestClient(app) as test_client:
            yield test_client


def session(client: TestClient, *, user_id: str = "demo-user") -> tuple[str, dict[str, str]]:
    response = client.post("/api/session", json={"user_id": user_id})
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    return session_id, {"X-Session-Id": session_id}


def test_retail_storefront_contract_includes_catalog_detail_cart_and_orders(
    client: TestClient,
) -> None:
    session_id, headers = session(client)
    products = client.get("/api/products").json()["products"]
    assert products
    product = next(item for item in products if not item["options"] and item["in_stock"])

    detail = client.get(f"/api/products/{product['product_id']}")
    assert detail.status_code == 200
    assert "price_intelligence" in detail.json()
    assert client.get("/api/cart", headers=headers).json()["items"] == []

    added = client.post(
        "/api/cart/add", json={"product_id": product["product_id"], "quantity": 1}, headers=headers
    )
    assert added.status_code == 200
    assert added.json()["cart"]["item_count"] == 1
    assert client.get("/api/orders", headers=headers).status_code == 200
    assert session_id


def test_vertical_factory_uses_source_merchant_path_and_travel_catalog(client: TestClient) -> None:
    app = create_app("test", vertical="travel")
    with TestClient(app) as travel_client:
        assert travel_client.post("/api/merchant/session").status_code == 200
        assert travel_client.get("/api/products").status_code == 200


def test_telecom_direct_add_restrictions_and_account_contract(client: TestClient) -> None:
    app = create_app("test", vertical="telecom")
    with TestClient(app) as telecom_client:
        response = telecom_client.post("/api/session", json={"user_id": "demo-user"})
        headers = {"X-Session-Id": response.json()["session_id"]}
        products = telecom_client.get("/api/products").json()["products"]
        device = next(product for product in products if product["category"] == "devices")
        plan = next(product for product in products if product["category"] == "plans")

        assert telecom_client.get("/api/account", headers=headers).json()["account"] is not None
        assert (
            telecom_client.post(
                "/api/cart/add", json={"product_id": plan["product_id"]}, headers=headers
            ).status_code
            == 400
        )
        assert (
            telecom_client.post(
                "/api/cart/add", json={"product_id": device["product_id"]}, headers=headers
            ).status_code
            == 200
        )


def test_entertainment_hold_waitlist_offer_and_transfer_contract(client: TestClient) -> None:
    app = create_app("test", vertical="entertainment")
    with TestClient(app) as tickets_client:
        response = tickets_client.post("/api/session")
        headers = {"X-Session-Id": response.json()["session_id"]}
        host = app.state.retail_host
        backend = host._storefronts["entertainment"]
        available_id = next(pid for pid in backend.products if backend.engine.remaining(pid) > 0)
        sold_out_id = next(pid for pid in backend.products if backend.engine.remaining(pid) == 0)

        added = tickets_client.post(
            "/api/cart/add", json={"product_id": available_id}, headers=headers
        )
        assert added.status_code == 200
        hold_id = tickets_client.get("/api/holds", headers=headers).json()["holds"][0]["hold_id"]
        assert (
            tickets_client.post(
                "/api/holds/release", json={"hold_id": hold_id}, headers=headers
            ).status_code
            == 200
        )

        executor = host.session("entertainment", response.json()["session_id"]).shopping_executor
        assert executor is not None
        executor.state.remember_products([backend.get_live_product(sold_out_id)])
        assert (
            tickets_client.post(
                "/api/waitlist/join",
                json={"product_id": sold_out_id, "quantity": 1},
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            tickets_client.post(
                "/api/demo/return", json={"product_id": sold_out_id, "quantity": 1}
            ).status_code
            == 200
        )
        offer_id = tickets_client.get("/api/waitlist", headers=headers).json()["offers"][0][
            "offer_id"
        ]
        assert (
            tickets_client.post(
                "/api/waitlist/claim", json={"offer_id": offer_id}, headers=headers
            ).status_code
            == 200
        )

        wallet = tickets_client.get("/api/tickets", headers=headers).json()["tickets"]
        assert wallet
        transfer = tickets_client.post(
            "/api/tickets/transfer",
            json={"ticket_ids": [wallet[0]["ticket_id"]], "recipient": "fan@example.test"},
            headers=headers,
        )
        assert transfer.status_code == 200
        assert tickets_client.post(
            "/api/tickets/transfer/cancel",
            json={"transfer_id": transfer.json()["transfer"]["transfer_id"]},
            headers=headers,
        ).json() == {"ok": True, "status": "cancelled"}


def test_storefront_memory_reset_and_health_contract(client: TestClient) -> None:
    session_id, headers = session(client)
    app = client.app
    app.state.retail_host.session("shopping", session_id).memory.save("color", "blue")

    assert client.get("/api/memory", headers=headers).json() == {
        "facts": [{"key": "color", "value": "blue"}]
    }
    assert client.patch(
        "/api/memory", json={"key": "color", "value": "green"}, headers=headers
    ).json() == {"ok": True, "fact": {"key": "color", "value": "green"}}
    assert client.request(
        "DELETE", "/api/memory", json={"key": "color"}, headers=headers
    ).json() == {
        "ok": True,
        "deleted": "color",
    }
    reset = client.post("/api/reset", json={"purge_memory": True}, headers=headers)
    assert reset.status_code == 200 and reset.json()["session_id"] != session_id
    health = client.get("/api/health").json()
    assert health["ok"] and health["store"] == "ACME" and health["model"] == "test"
    assert client.get("/products/AR-1002.webp").status_code == 200
    assert client.get("/products/missing.webp").status_code == 404


@pytest.mark.parametrize(
    ("vertical", "read_path", "overview_key"),
    [
        ("retail", None, "trends"),
        ("travel", "/occupancy", "today"),
        ("telecom", "/base", "today"),
        ("entertainment", "/pacing", "today"),
    ],
)
def test_source_merchant_portal_contract(
    vertical: str, read_path: str | None, overview_key: str
) -> None:
    app = create_app("test", vertical=vertical)
    with TestClient(app) as portal:
        started = portal.post("/api/merchant/session")
        assert started.status_code == 200
        headers = {"X-Session-Id": started.json()["session_id"]}
        assert "merchant_id" in started.json() and "operator" in started.json()
        overview = portal.get("/api/merchant/overview", headers=headers)
        assert overview.status_code == 200 and overview_key in overview.json()
        listings = portal.get("/api/merchant/listings", headers=headers).json()
        assert listings["total"] and listings["listings"]
        listing_id = listings["listings"][0]["listing_id"]
        assert (
            portal.get(f"/api/merchant/listings/{listing_id}", headers=headers).status_code == 200
        )
        assert portal.get("/api/merchant/alerts", headers=headers).status_code == 200
        assert portal.get("/api/merchant/health").json()["role"] == "merchant"
        if read_path:
            assert portal.get(f"/api/merchant{read_path}", headers=headers).status_code == 200
        assert (
            portal.post("/api/merchant/changes/missing/discard", headers=headers).status_code == 400
        )
        assert portal.post("/api/merchant/reset", json={}, headers=headers).status_code == 200


def test_ticket_errors_match_source_statuses() -> None:
    app = create_app("test", vertical="entertainment")
    with TestClient(app) as tickets_client:
        first = tickets_client.post("/api/session", json={"user_id": "demo-user"}).json()
        second = tickets_client.post("/api/session", json={"user_id": "other-user"}).json()
        headers = {"X-Session-Id": first["session_id"]}
        other_headers = {"X-Session-Id": second["session_id"]}
        backend = app.state.retail_host._storefronts["entertainment"]
        available_id = next(pid for pid in backend.products if backend.engine.remaining(pid) > 0)
        assert (
            tickets_client.post(
                "/api/cart/add", json={"product_id": available_id}, headers=headers
            ).status_code
            == 200
        )
        hold_id = tickets_client.get("/api/holds", headers=headers).json()["holds"][0]["hold_id"]
        assert (
            tickets_client.post(
                "/api/holds/release", json={"hold_id": hold_id}, headers=other_headers
            ).status_code
            == 403
        )
        assert (
            tickets_client.post(
                "/api/holds/release", json={"hold_id": "missing"}, headers=headers
            ).status_code
            == 404
        )
        executor = app.state.retail_host.session(
            "entertainment", first["session_id"]
        ).shopping_executor
        assert executor is not None
        executor.state.remember_products([backend.get_live_product(available_id)])
        assert (
            tickets_client.post(
                "/api/waitlist/join", json={"product_id": available_id}, headers=headers
            ).status_code
            == 409
        )
