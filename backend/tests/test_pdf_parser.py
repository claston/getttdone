from pathlib import Path

import pytest

from app.application.errors import InvalidFileContentError
from app.application.pdf_parser import parse_pdf_transactions


def test_parse_pdf_transactions_with_real_sample_file() -> None:
    sample_path = Path(__file__).resolve().parents[1] / "samples" / "NU_150702837_01NOV2023_30NOV2023.pdf"
    raw = sample_path.read_bytes()

    result = parse_pdf_transactions(raw)

    assert result.layout.layout_name in {"nubank_statement_ptbr", "generic_statement_ptbr"}
    assert len(result.transactions) > 0
    assert any(item.amount > 0 for item in result.transactions)
    assert any(item.amount < 0 for item in result.transactions)


def test_parse_pdf_transactions_with_itau_inline_layout_sample() -> None:
    sample_path = Path(__file__).resolve().parents[1] / "samples" / "itau_extrato_032026.pdf"
    raw = sample_path.read_bytes()

    result = parse_pdf_transactions(raw)

    assert result.layout.layout_name in {"itau_statement_ptbr", "generic_statement_ptbr"}
    assert len(result.transactions) > 0
    assert any("SALDO DO DIA" not in item.description.upper() for item in result.transactions)
    assert any(item.amount > 0 for item in result.transactions)
    assert any(item.amount < 0 for item in result.transactions)


def test_parse_pdf_transactions_raises_when_no_transaction_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.application import pdf_parser

    monkeypatch.setattr(pdf_parser, "_extract_pdf_page_texts", lambda raw_bytes: ["SEM DADOS DE MOVIMENTACOES"])

    with pytest.raises(
        InvalidFileContentError,
        match="unsupported table layout|no recognizable transaction row pattern",
    ):
        parse_pdf_transactions(b"%PDF-1.4 fake")
