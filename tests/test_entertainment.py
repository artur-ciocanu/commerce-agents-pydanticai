from commerce_agents.reference.adapter import EntertainmentBackendAdapter


async def test_transplanted_ticketing_backend_exposes_live_event_catalog() -> None:
    backend = EntertainmentBackendAdapter("ticketing-contract")

    tickets = await backend.search_products("headliner", None, 8)
    assert tickets

    product_id = tickets[0].product_id
    await backend.add_to_cart("ticketing-contract", product_id, 1)
    assert (await backend.get_cart("ticketing-contract")).items[0].product_id == product_id
