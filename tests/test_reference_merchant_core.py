from commerce_agents.reference.merchant_agent import (
    ChangeItem,
    ChangeKind,
    ChangeLedger,
    GuardrailViolation,
    MerchantAgentConfig,
    check_analysis_sql,
)


def test_vendored_merchant_ledger_rechecks_source_guardrails() -> None:
    config = MerchantAgentConfig(max_price_delta_pct=20)
    ledger = ChangeLedger(config)

    change = ledger.stage(
        kind=ChangeKind.PRICE_UPDATE,
        summary="Price adjustment",
        items=[ChangeItem(target="listing-1", field="price", before=100, after=110)],
        actor="operator-1",
    )
    config.max_price_delta_pct = 5

    try:
        ledger.apply(change.change_id, "operator-1")
    except GuardrailViolation as error:
        assert "per-change limit" in str(error)
    else:
        raise AssertionError("The source ledger must re-check guardrails before apply.")


def test_vendored_analysis_sql_check_refuses_non_select_statements() -> None:
    assert check_analysis_sql("SELECT listing_id FROM listings") is None
    non_select = check_analysis_sql("DELETE FROM listings")
    commented = check_analysis_sql("SELECT 1 -- hidden")

    assert non_select is not None and "only SELECT" in non_select
    assert commented is not None and "comments" in commented
