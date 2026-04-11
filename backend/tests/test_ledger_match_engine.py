from app.application.ledger_match_engine import match_exact_1to1
from app.application.models import NormalizedTransaction


def test_match_exact_1to1_matches_only_same_date_and_amount() -> None:
    bank_rows = [
        NormalizedTransaction(date="2026-04-01", description="A", amount=-100.0, type="outflow"),
        NormalizedTransaction(date="2026-04-01", description="B", amount=50.0, type="inflow"),
        NormalizedTransaction(date="2026-04-02", description="C", amount=-20.0, type="outflow"),
    ]
    sheet_rows = [
        NormalizedTransaction(date="2026-04-01", description="X", amount=-100.0, type="outflow"),
        NormalizedTransaction(date="2026-04-02", description="Y", amount=-20.0, type="outflow"),
        NormalizedTransaction(date="2026-04-03", description="Z", amount=50.0, type="inflow"),
    ]

    result = match_exact_1to1(bank_rows=bank_rows, sheet_rows=sheet_rows)

    assert result.exact_matches_count == 2
    assert result.bank_unmatched_count == 1
    assert result.sheet_unmatched_count == 1
    assert result.matches[0].match_rule == "exact"
    assert result.matches[0].reason == "matched_exact_value_and_date"


def test_match_exact_1to1_does_not_reuse_sheet_row() -> None:
    bank_rows = [
        NormalizedTransaction(date="2026-04-01", description="A", amount=-100.0, type="outflow"),
        NormalizedTransaction(date="2026-04-01", description="B", amount=-100.0, type="outflow"),
    ]
    sheet_rows = [
        NormalizedTransaction(date="2026-04-01", description="X", amount=-100.0, type="outflow"),
    ]

    result = match_exact_1to1(bank_rows=bank_rows, sheet_rows=sheet_rows)

    assert result.exact_matches_count == 1
    assert result.bank_unmatched_count == 1
    assert result.sheet_unmatched_count == 0
