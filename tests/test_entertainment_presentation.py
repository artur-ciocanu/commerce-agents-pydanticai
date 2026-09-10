from commerce_agents.entertainment_presentation import event_pacing, hold_view
from commerce_agents.shopping import Product


def test_ticketing_presentation_uses_seen_ticket_ids_and_backend_pacing() -> None:
    event = hold_view(
        {"product_ids": ["ticket", "invented"]},
        {"ticket": Product(product_id="ticket", title="Ticket", price=50)},
    )
    pacing = event_pacing({"events": [{"event_id": "show", "tiers": []}]})

    assert [ticket["product_id"] for ticket in event.data["payload"]["tickets"]] == ["ticket"]
    assert pacing.data["payload"]["events"][0]["event_id"] == "show"
