from commerce_agents.reference.merchant_agent import MerchantSessionContext, PriceUpdateItem
from commerce_agents.reference.merchant_retail import MockRetailMerchant
from commerce_agents.reference.retail import MockRetail


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
