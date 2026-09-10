from commerce_agents.retail import MERCHANT_SKILLS, SHOPPING_SKILLS


def test_vendored_source_skills_are_available_to_the_registry() -> None:
    assert "purchase-research" in SHOPPING_SKILLS.names
    assert "pricing-promotions" in MERCHANT_SKILLS.names
    assert SHOPPING_SKILLS.get_instructions("customer-care")
    assert MERCHANT_SKILLS.get_instructions("catalog-listings")
