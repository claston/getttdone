from app.application.ledger_match_models import LedgerExactMatch, LedgerMatchResult
from app.application.models import NormalizedTransaction


def match_exact_1to1(
    bank_rows: list[NormalizedTransaction],
    sheet_rows: list[NormalizedTransaction],
) -> LedgerMatchResult:
    matches: list[LedgerExactMatch] = []
    used_sheet_indexes: set[int] = set()

    for bank_index, bank_row in enumerate(bank_rows):
        for sheet_index, sheet_row in enumerate(sheet_rows):
            if sheet_index in used_sheet_indexes:
                continue
            if bank_row.date != sheet_row.date:
                continue
            if round(bank_row.amount, 2) != round(sheet_row.amount, 2):
                continue

            matches.append(
                LedgerExactMatch(
                    bank_index=bank_index,
                    sheet_index=sheet_index,
                    date=bank_row.date,
                    amount=round(bank_row.amount, 2),
                    match_rule="exact",
                    reason="matched_exact_value_and_date",
                )
            )
            used_sheet_indexes.add(sheet_index)
            break

    exact_matches_count = len(matches)
    bank_unmatched_count = len(bank_rows) - exact_matches_count
    sheet_unmatched_count = len(sheet_rows) - exact_matches_count
    return LedgerMatchResult(
        matches=matches,
        exact_matches_count=exact_matches_count,
        bank_unmatched_count=bank_unmatched_count,
        sheet_unmatched_count=sheet_unmatched_count,
    )
