from __future__ import annotations

import re
from dataclasses import dataclass

from app.application.normalization.pdf_amount_tokens import AmountToken, find_amount_tokens, parse_pdf_amount
from app.application.normalization.pdf_row_date_rules import parse_row_date
from app.application.parsers.pdf.layout_specific.contract import (
    LayoutSpecificParseContext,
    LayoutSpecificParseResult,
)
from app.application.parsers.pdf.layout_specific.shared import build_parsed_transaction, normalize_text
from app.application.parsers.pdf.models import _ParsedTransaction, _PdfLine

PAGBANK_SIMPLE_LAYOUT = "pagbank_extrato_conta_corrente_simples_v1"
PAGSEGURO_BLOCKED_LAYOUT = "pagseguro_relatorio_conta_bloqueada_v1"
PAGBANK_OPERATIONS_LAYOUT = "pagbank_extrato_transacoes_operacionais_v1"

_ALL_LAYOUTS = frozenset({PAGBANK_SIMPLE_LAYOUT, PAGSEGURO_BLOCKED_LAYOUT, PAGBANK_OPERATIONS_LAYOUT})
_DATE_ROW_PATTERN = re.compile(r"^\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+(?P<rest>.+)$")
_DATETIME_ROW_PATTERN = re.compile(
    r"^\s*(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<rest>.+)$"
)
_BLOCKED_ROW_PATTERN = re.compile(
    r"^(?P<code>[A-Z0-9]{16,})\s+(?P<description>.+?)\s+"
    r"(?P<amount>[+\-]?(?:\d{1,3}(?:[.,]\d{3})*|\d+)[.,]\d{2})\s+"
    r"(?P<balance>[+\-]?(?:(?:\d{1,3}(?:[.,]\d{3})*|\d+)[.,]\d{2}|\d+))"
    r"(?:\s+\d+)?\s*$",
    flags=re.IGNORECASE,
)
_REFERENCE_PATTERN = re.compile(
    r"\b(?:[A-F0-9]{20,}|[A-F0-9]{8}(?:-[A-F0-9]{4}){3}-[A-F0-9]{12})\b",
    flags=re.IGNORECASE,
)
_DEBIT_OPERATION_TOKENS = ("SAQUE", "TRANSFERENCIA", "PAGAMENTO", "ESTORNO DE VENDA")
_REJECTED_STATUS_TOKENS = ("CANCELADA", "NEGADA", "REPROVADA")


@dataclass(frozen=True, slots=True)
class _PendingOperation:
    date: str
    operation_type: str
    reference: str | None
    source: _PdfLine


@dataclass(frozen=True, slots=True)
class PagBankLayoutParser:
    layout_names: frozenset[str] = _ALL_LAYOUTS

    def parse(
        self,
        *,
        layout_name: str,
        lines: list[_PdfLine],
        context: LayoutSpecificParseContext,
    ) -> LayoutSpecificParseResult | None:
        del context
        if layout_name == PAGBANK_SIMPLE_LAYOUT:
            rows = _parse_simple_account_rows(lines)
        elif layout_name == PAGSEGURO_BLOCKED_LAYOUT:
            rows = _parse_blocked_account_rows(lines)
        elif layout_name == PAGBANK_OPERATIONS_LAYOUT:
            rows = _parse_operation_rows(lines)
        else:
            return None

        if not rows:
            return None
        return LayoutSpecificParseResult(
            rows=rows,
            selected_parser="layout_specific_pagbank",
            selection_reason=f"layout_specific_pagbank:{layout_name}",
        )


def _parse_simple_account_rows(lines: list[_PdfLine]) -> list[_ParsedTransaction]:
    rows: list[_ParsedTransaction] = []
    for line in lines:
        match = _DATE_ROW_PATTERN.match(line.text)
        if match is None:
            continue
        amount_tokens = tuple(find_amount_tokens(match.group("rest")))
        if not amount_tokens:
            continue
        description = _clean_description(match.group("rest"), amount_tokens=amount_tokens)
        if "SALDO DO DIA" in normalize_text(description):
            continue
        amount_token = amount_tokens[-1]
        rows.append(
            build_parsed_transaction(
                date=parse_row_date(match.group("date"), fallback_year=None),
                description=description,
                amount=parse_pdf_amount(amount_token.value),
                source_page=line.page_number,
                source_line=line.line_number,
            )
        )
    return rows


def _parse_blocked_account_rows(lines: list[_PdfLine]) -> list[_ParsedTransaction]:
    rows: list[_ParsedTransaction] = []
    for line in lines:
        date_match = _DATETIME_ROW_PATTERN.match(line.text)
        if date_match is None:
            continue
        row_match = _BLOCKED_ROW_PATTERN.match(date_match.group("rest"))
        if row_match is None:
            continue
        rows.append(
            build_parsed_transaction(
                date=parse_row_date(date_match.group("date"), fallback_year=None),
                description=f"{row_match.group('description')} CONTA BLOQUEADA",
                amount=parse_pdf_amount(row_match.group("amount")),
                running_balance=parse_pdf_amount(row_match.group("balance")),
                external_reference_id=row_match.group("code"),
                source_page=line.page_number,
                source_line=line.line_number,
                has_explicit_amount_sign=True,
            )
        )
    return rows


def _parse_operation_rows(lines: list[_PdfLine]) -> list[_ParsedTransaction]:
    rows: list[_ParsedTransaction] = []
    pending: _PendingOperation | None = None
    for line in lines:
        date_match = _DATETIME_ROW_PATTERN.match(line.text)
        if date_match is not None:
            pending = _build_pending_operation(date_match=date_match, source=line)
            amount_tokens = tuple(find_amount_tokens(date_match.group("rest")))
            if pending is not None and len(amount_tokens) >= 3:
                rows.append(_build_operation_row(pending=pending, details=line.text, amount_tokens=amount_tokens))
                pending = None
            continue
        if pending is None:
            continue
        amount_tokens = tuple(find_amount_tokens(line.text))
        if len(amount_tokens) < 3:
            continue
        if any(token in normalize_text(line.text) for token in _REJECTED_STATUS_TOKENS):
            pending = None
            continue
        rows.append(_build_operation_row(pending=pending, details=line.text, amount_tokens=amount_tokens))
        pending = None
    return rows


def _build_pending_operation(*, date_match: re.Match[str], source: _PdfLine) -> _PendingOperation | None:
    rest = date_match.group("rest")
    reference_match = _REFERENCE_PATTERN.search(rest)
    if reference_match is None:
        return None
    operation_type = rest[reference_match.end() :].strip(" -")
    if not operation_type:
        return None
    return _PendingOperation(
        date=parse_row_date(date_match.group("date"), fallback_year=None),
        operation_type=operation_type,
        reference=reference_match.group(0),
        source=source,
    )


def _build_operation_row(
    *,
    pending: _PendingOperation,
    details: str,
    amount_tokens: tuple[AmountToken, ...],
) -> _ParsedTransaction:
    net_amount_token = amount_tokens[-1]
    raw_amount = parse_pdf_amount(net_amount_token.value)
    normalized_type = normalize_text(pending.operation_type)
    amount = -abs(raw_amount) if any(token in normalized_type for token in _DEBIT_OPERATION_TOKENS) else raw_amount
    counterparty = re.split(r"\bAPROVADA\b", details, maxsplit=1, flags=re.IGNORECASE)[0].strip(" -")
    description = pending.operation_type
    if counterparty and counterparty != pending.operation_type:
        description = f"{description} {counterparty}"
    return build_parsed_transaction(
        date=pending.date,
        description=description,
        amount=amount,
        external_reference_id=pending.reference,
        source_page=pending.source.page_number,
        source_line=pending.source.line_number,
        has_explicit_amount_sign=True,
    )


def _clean_description(raw_text: str, *, amount_tokens: tuple[AmountToken, ...]) -> str:
    value = raw_text
    for token in sorted(amount_tokens, key=lambda item: item.start, reverse=True):
        value = value[: token.start] + " " + value[token.end :]
    value = re.sub(r"(?:^|\s)[+\-]?\s*R\$\s*$", " ", value, flags=re.IGNORECASE)
    return " ".join(value.strip(" -|:").split())
