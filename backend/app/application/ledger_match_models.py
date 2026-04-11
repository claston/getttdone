from dataclasses import dataclass


@dataclass
class LedgerExactMatch:
    bank_index: int
    sheet_index: int
    date: str
    amount: float
    match_rule: str
    reason: str


@dataclass
class LedgerMatchResult:
    matches: list[LedgerExactMatch]
    exact_matches_count: int
    bank_unmatched_count: int
    sheet_unmatched_count: int
