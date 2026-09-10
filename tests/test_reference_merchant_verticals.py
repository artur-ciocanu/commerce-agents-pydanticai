from commerce_agents.reference.merchant_agent import MerchantSessionContext
from commerce_agents.reference.merchant_telecom import MockTelecomMerchant
from commerce_agents.reference.merchant_travel import MockTravelMerchant
from commerce_agents.reference.telecom import MockTelecom
from commerce_agents.reference.travel import MockTravel


async def test_vendored_travel_and_telecom_merchants_read_vertical_context() -> None:
    session = MerchantSessionContext(session_id="s", merchant_id="m", operator="operator-1")
    travel = MockTravelMerchant(MockTravel())
    telecom = MockTelecomMerchant(MockTelecom())

    travel_snapshot = await travel.get_business_snapshot(session)
    telecom_snapshot = await telecom.get_business_snapshot(session)
    travel_context = await travel.get_merchant_context(session)
    telecom_context = await telecom.get_merchant_context(session)

    assert travel_snapshot.orders > 0
    assert telecom_snapshot.orders > 0
    assert travel_context is not None and travel_context["supplier"] == travel.supplier_name
    assert telecom_context is not None and telecom_context["carrier"] == telecom.carrier_name
