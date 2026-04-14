import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from app.application.ledger_match_models import (
    LedgerClassificationResult,
    LedgerMatchResult,
    LedgerReconciliationRow,
)
from app.application.models import NormalizedTransaction

_DIVERGENCE_DATE_TOLERANCE_DAYS = 2
_DIVERGENCE_DESCRIPTION_SIMILARITY_THRESHOLD = 0.80
_FEE_SUGGESTION_MAX_DELTA = 10.0
_FEE_SUGGESTION_MIN_DELTA = 0.01
_FEE_AMOUNT_TOLERANCE = 0.02
_FEE_KEYWORD_PATTERN = re.compile(r"\b(TARIFA|TAXA|IOF|ENCARGO|JUROS|CUSTO)\b", re.IGNORECASE)


@dataclass
class _DivergentPairCandidate:
    bank_idx: int
    sheet_idx: int
    reason: str
    suggestion_type: str | None = None
    suggested_fee_source: str | None = None
    suggested_fee_idx: int | None = None
    suggested_delta_amount: float | None = None
    suggestion_reason: str | None = None


def classify_reconciliation_rows(
    bank_rows: list[NormalizedTransaction],
    sheet_rows: list[NormalizedTransaction],
    match_result: LedgerMatchResult,
) -> LedgerClassificationResult:
    rows: list[LedgerReconciliationRow] = []

    bank_row_ids = [_row_id("bank", idx) for idx in range(len(bank_rows))]
    sheet_row_ids = [_row_id("sheet", idx) for idx in range(len(sheet_rows))]

    matched_bank_indexes = {match.bank_index for match in match_result.matches}
    matched_sheet_indexes = {match.sheet_index for match in match_result.matches}

    for match in match_result.matches:
        bank = bank_rows[match.bank_index]
        sheet = sheet_rows[match.sheet_index]
        bank_id = bank_row_ids[match.bank_index]
        sheet_id = sheet_row_ids[match.sheet_index]
        status, reason = _classify_matched_pair(
            bank=bank,
            sheet=sheet,
            fallback_reason=match.reason,
        )
        rows.append(
            LedgerReconciliationRow(
                row_id=bank_id,
                source="bank",
                date=bank.date,
                description=bank.description,
                amount=bank.amount,
                status=status,
                match_rule=match.match_rule,
                matched_row_id=sheet_id,
                reason=reason,
            )
        )
        rows.append(
            LedgerReconciliationRow(
                row_id=sheet_id,
                source="sheet",
                date=sheet.date,
                description=sheet.description,
                amount=sheet.amount,
                status=status,
                match_rule=match.match_rule,
                matched_row_id=bank_id,
                reason=reason,
            )
        )

    unmatched_bank_indexes = [idx for idx in range(len(bank_rows)) if idx not in matched_bank_indexes]
    unmatched_sheet_indexes = [idx for idx in range(len(sheet_rows)) if idx not in matched_sheet_indexes]

    divergent_pairs = _pair_divergent_candidates(
        bank_rows=bank_rows,
        sheet_rows=sheet_rows,
        unmatched_bank_indexes=unmatched_bank_indexes,
        unmatched_sheet_indexes=unmatched_sheet_indexes,
    )

    divergent_bank_indexes = {pair.bank_idx for pair in divergent_pairs}
    divergent_sheet_indexes = {pair.sheet_idx for pair in divergent_pairs}

    for pair in divergent_pairs:
        bank = bank_rows[pair.bank_idx]
        sheet = sheet_rows[pair.sheet_idx]
        bank_id = bank_row_ids[pair.bank_idx]
        sheet_id = sheet_row_ids[pair.sheet_idx]
        suggested_fee_row_id = _resolve_suggested_fee_row_id(
            pair=pair,
            bank_row_ids=bank_row_ids,
            sheet_row_ids=sheet_row_ids,
        )
        rows.append(
            LedgerReconciliationRow(
                row_id=bank_id,
                source="bank",
                date=bank.date,
                description=bank.description,
                amount=bank.amount,
                status="divergente",
                match_rule="none",
                matched_row_id=sheet_id,
                reason=pair.reason,
                suggestion_type=pair.suggestion_type,
                suggested_fee_row_id=suggested_fee_row_id,
                suggested_delta_amount=pair.suggested_delta_amount,
                suggestion_reason=pair.suggestion_reason,
            )
        )
        rows.append(
            LedgerReconciliationRow(
                row_id=sheet_id,
                source="sheet",
                date=sheet.date,
                description=sheet.description,
                amount=sheet.amount,
                status="divergente",
                match_rule="none",
                matched_row_id=bank_id,
                reason=pair.reason,
                suggestion_type=pair.suggestion_type,
                suggested_fee_row_id=suggested_fee_row_id,
                suggested_delta_amount=pair.suggested_delta_amount,
                suggestion_reason=pair.suggestion_reason,
            )
        )

    for bank_idx in unmatched_bank_indexes:
        if bank_idx in divergent_bank_indexes:
            continue
        bank = bank_rows[bank_idx]
        rows.append(
            LedgerReconciliationRow(
                row_id=bank_row_ids[bank_idx],
                source="bank",
                date=bank.date,
                description=bank.description,
                amount=bank.amount,
                status="pendente",
                match_rule="none",
                matched_row_id=None,
                reason="missing_in_sheet",
            )
        )

    for sheet_idx in unmatched_sheet_indexes:
        if sheet_idx in divergent_sheet_indexes:
            continue
        sheet = sheet_rows[sheet_idx]
        rows.append(
            LedgerReconciliationRow(
                row_id=sheet_row_ids[sheet_idx],
                source="sheet",
                date=sheet.date,
                description=sheet.description,
                amount=sheet.amount,
                status="pendente",
                match_rule="none",
                matched_row_id=None,
                reason="missing_in_bank",
            )
        )

    conciliated_count = sum(1 for row in rows if row.status == "conciliado")
    pending_count = sum(1 for row in rows if row.status == "pendente")
    divergent_count = sum(1 for row in rows if row.status == "divergente")

    return LedgerClassificationResult(
        rows=rows,
        conciliated_count=conciliated_count,
        pending_count=pending_count,
        divergent_count=divergent_count,
    )


def _classify_matched_pair(
    bank: NormalizedTransaction,
    sheet: NormalizedTransaction,
    fallback_reason: str,
) -> tuple[str, str]:
    bank_date = _parse_iso_date(bank.date)
    sheet_date = _parse_iso_date(sheet.date)
    if bank_date is not None and sheet_date is not None:
        day_distance = abs((bank_date - sheet_date).days)
        if day_distance > _DIVERGENCE_DATE_TOLERANCE_DAYS:
            return "divergente", "date_out_of_tolerance_window"

    return "conciliado", fallback_reason


def _pair_divergent_candidates(
    bank_rows: list[NormalizedTransaction],
    sheet_rows: list[NormalizedTransaction],
    unmatched_bank_indexes: list[int],
    unmatched_sheet_indexes: list[int],
) -> list[_DivergentPairCandidate]:
    pairs: list[_DivergentPairCandidate] = []
    used_sheet_indexes: set[int] = set()
    used_fee_sheet_indexes: set[int] = set()
    used_fee_bank_indexes: set[int] = set()

    for bank_idx in unmatched_bank_indexes:
        bank = bank_rows[bank_idx]
        bank_date = _parse_iso_date(bank.date)
        if bank_date is None:
            continue

        best_sheet_idx: int | None = None
        best_reason: str | None = None
        best_similarity: float = 0.0

        for sheet_idx in unmatched_sheet_indexes:
            if sheet_idx in used_sheet_indexes:
                continue

            sheet = sheet_rows[sheet_idx]

            sheet_date = _parse_iso_date(sheet.date)
            if sheet_date is None:
                continue

            similarity = _description_similarity(bank.description, sheet.description)
            if similarity < _DIVERGENCE_DESCRIPTION_SIMILARITY_THRESHOLD:
                continue

            amount_matches = round(bank.amount, 2) == round(sheet.amount, 2)
            day_distance = abs((bank_date - sheet_date).days)
            day_out_of_tolerance = day_distance > _DIVERGENCE_DATE_TOLERANCE_DAYS

            if amount_matches and not day_out_of_tolerance:
                continue

            reason = "date_out_of_tolerance_window" if amount_matches else "amount_mismatch"
            if similarity > best_similarity:
                best_similarity = similarity
                best_sheet_idx = sheet_idx
                best_reason = reason

        if best_sheet_idx is not None and best_reason is not None:
            used_sheet_indexes.add(best_sheet_idx)
            candidate = _DivergentPairCandidate(
                bank_idx=bank_idx,
                sheet_idx=best_sheet_idx,
                reason=best_reason,
            )
            if best_reason == "amount_mismatch":
                _attach_fee_suggestion_if_any(
                    candidate=candidate,
                    bank_rows=bank_rows,
                    sheet_rows=sheet_rows,
                    unmatched_bank_indexes=unmatched_bank_indexes,
                    unmatched_sheet_indexes=unmatched_sheet_indexes,
                    used_fee_bank_indexes=used_fee_bank_indexes,
                    used_fee_sheet_indexes=used_fee_sheet_indexes,
                )
            pairs.append(candidate)

    return pairs


def _attach_fee_suggestion_if_any(
    candidate: _DivergentPairCandidate,
    bank_rows: list[NormalizedTransaction],
    sheet_rows: list[NormalizedTransaction],
    unmatched_bank_indexes: list[int],
    unmatched_sheet_indexes: list[int],
    used_fee_bank_indexes: set[int],
    used_fee_sheet_indexes: set[int],
) -> None:
    bank = bank_rows[candidate.bank_idx]
    sheet = sheet_rows[candidate.sheet_idx]

    delta = round(abs(abs(bank.amount) - abs(sheet.amount)), 2)
    if delta < _FEE_SUGGESTION_MIN_DELTA or delta > _FEE_SUGGESTION_MAX_DELTA:
        return

    bank_date = _parse_iso_date(bank.date)
    sheet_date = _parse_iso_date(sheet.date)
    if bank_date is None or sheet_date is None:
        return
    if abs((bank_date - sheet_date).days) > _DIVERGENCE_DATE_TOLERANCE_DAYS:
        return

    sheet_fee_idx = _find_fee_row_candidate(
        source_rows=sheet_rows,
        source_indexes=unmatched_sheet_indexes,
        primary_index=candidate.sheet_idx,
        counterpart_date=bank_date,
        expected_delta=delta,
        used_indexes=used_fee_sheet_indexes,
    )
    if sheet_fee_idx is not None:
        used_fee_sheet_indexes.add(sheet_fee_idx)
        candidate.suggestion_type = "fee_adjustment_candidate"
        candidate.suggested_fee_source = "sheet"
        candidate.suggested_fee_idx = sheet_fee_idx
        candidate.suggested_delta_amount = delta
        candidate.suggestion_reason = "possible_fee_row_for_amount_delta"
        return

    bank_fee_idx = _find_fee_row_candidate(
        source_rows=bank_rows,
        source_indexes=unmatched_bank_indexes,
        primary_index=candidate.bank_idx,
        counterpart_date=sheet_date,
        expected_delta=delta,
        used_indexes=used_fee_bank_indexes,
    )
    if bank_fee_idx is not None:
        used_fee_bank_indexes.add(bank_fee_idx)
        candidate.suggestion_type = "fee_adjustment_candidate"
        candidate.suggested_fee_source = "bank"
        candidate.suggested_fee_idx = bank_fee_idx
        candidate.suggested_delta_amount = delta
        candidate.suggestion_reason = "possible_fee_row_for_amount_delta"


def _find_fee_row_candidate(
    source_rows: list[NormalizedTransaction],
    source_indexes: list[int],
    primary_index: int,
    counterpart_date: date,
    expected_delta: float,
    used_indexes: set[int],
) -> int | None:
    best_idx: int | None = None
    best_date_distance: int | None = None
    best_amount_distance: float | None = None

    for idx in source_indexes:
        if idx == primary_index or idx in used_indexes:
            continue
        row = source_rows[idx]
        if not _looks_like_fee_row(row.description):
            continue

        row_date = _parse_iso_date(row.date)
        if row_date is None:
            continue
        date_distance = abs((row_date - counterpart_date).days)
        if date_distance > _DIVERGENCE_DATE_TOLERANCE_DAYS:
            continue

        amount_distance = abs(abs(round(row.amount, 2)) - expected_delta)
        if amount_distance > _FEE_AMOUNT_TOLERANCE:
            continue

        if (
            best_idx is None
            or date_distance < best_date_distance
            or (
                best_date_distance is not None
                and date_distance == best_date_distance
                and best_amount_distance is not None
                and amount_distance < best_amount_distance
            )
        ):
            best_idx = idx
            best_date_distance = date_distance
            best_amount_distance = amount_distance

    return best_idx


def _looks_like_fee_row(description: str) -> bool:
    return bool(_FEE_KEYWORD_PATTERN.search(description or ""))


def _resolve_suggested_fee_row_id(
    pair: _DivergentPairCandidate,
    bank_row_ids: list[str],
    sheet_row_ids: list[str],
) -> str | None:
    if pair.suggested_fee_idx is None or pair.suggested_fee_source is None:
        return None
    if pair.suggested_fee_source == "bank":
        return bank_row_ids[pair.suggested_fee_idx]
    if pair.suggested_fee_source == "sheet":
        return sheet_row_ids[pair.suggested_fee_idx]
    return None


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _description_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _row_id(source: str, index: int) -> str:
    return f"{source}_{index + 1:03d}"
