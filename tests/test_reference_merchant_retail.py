from commerce_agents.reference.merchant_agent import MerchantSessionContext, PriceUpdateItem
from commerce_agents.reference.merchant_retail import MockRetailMerchant
from commerce_agents.reference.retail import MockRetail
from commerce_agents.source_merchant import SourceMerchantExecutor


async def test_vendored_retail_merchant_stages_and_applies_a_live_price_change() -> None:
    storefront = MockRetail()
    merchant = MockRetailMerchant(storefront)
    session = MerchantSessionContext(
        session_id="merchant-session", merchant_id="acme-retail", operator="operator-1"
    )
    listing = merchant.all_listings()[0]
    before = storefront.product(listing.listing_id)
    assert before is not None

    details = await merchant.get_listing(session, listing.listing_id)
    assert details is not None
    staged = await merchant.stage_price_update(
        session,
        [PriceUpdateItem(listing_id=listing.listing_id, new_price=round(listing.price * 1.1, 2))],
    )
    applied = await merchant.apply_change(session, staged.change_id)
    after = storefront.product(listing.listing_id)

    assert applied.status == "applied"
    assert after is not None and after.price == staged.items[0].after


async def test_source_executor_enforces_provenance_and_host_approval() -> None:
    backend = MockRetailMerchant(MockRetail())
    executor = SourceMerchantExecutor(backend, "merchant-session")
    listing_id = backend.all_listings()[0].listing_id

    listing = backend.all_listings()[0]
    await executor.execute("get_listing", {"listing_id": listing_id})
    staged = await executor.execute(
        "stage_price_update",
        {"items": [{"listing_id": listing_id, "new_price": round(listing.price * 1.1, 2)}]},
    )
    change_id = staged.events[0].data["change"]["change_id"]
    blocked = await executor.execute("apply_change", {"change_id": change_id})
    executor.approve(change_id)
    applied = await executor.execute("apply_change", {"change_id": change_id})

    assert blocked.blocked == "host_approval"
    assert applied.events[0].data["change"]["status"] == "applied"
