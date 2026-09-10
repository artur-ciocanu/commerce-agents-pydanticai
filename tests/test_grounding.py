from commerce_agents.grounding import shopping_grounding_tools


def test_source_shopping_grounding_precedence_and_product_provenance() -> None:
    assert shopping_grounding_tools("What is your return policy?", set())[0][0] == "search_policies"
    assert shopping_grounding_tools("Where is my order?", set())[0][0] == "get_orders"
    assert shopping_grounding_tools("Tell me about AM-PLAN-101", set()) == [
        ("get_product_details", {"product_id": "AM-PLAN-101"})
    ]
    assert shopping_grounding_tools("Tell me about AM-PLAN-101", {"AM-PLAN-101"}) == []
