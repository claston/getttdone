from io import BytesIO

import pytest
from openpyxl import Workbook

from app.application.errors import InvalidFileContentError
from app.application.xlsx_parser import parse_xlsx_transactions


def _build_xlsx_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parse_xlsx_transactions_from_first_sheet() -> None:
    raw = _build_xlsx_bytes(
        [
            ["Data", "Descricao", "Valor"],
            ["01/04/2026", "MERCADO", "-120,50"],
            ["02/04/2026", "PIX RECEBIDO", "1.350,00"],
            [None, None, None],
        ]
    )

    rows = parse_xlsx_transactions(raw)

    assert len(rows) == 2
    assert rows[0].date == "2026-04-01"
    assert rows[0].description == "MERCADO"
    assert rows[0].amount == -120.50
    assert rows[0].type == "outflow"
    assert rows[1].amount == 1350.00
    assert rows[1].type == "inflow"


def test_parse_xlsx_transactions_ignores_preamble_rows_and_accepts_alias_headers() -> None:
    raw = _build_xlsx_bytes(
        [
            ["Relatorio de movimentacoes", None, None],
            ["Gerado em", "15/04/2026", None],
            ["Data Pgto", "Valor Liquido (R$)", "Historico Lanc."],
            ["01/04/2026", "1.200,00", "RECEBIMENTO CLIENTE"],
            ["02/04/2026", "-250,50", "PAGAMENTO FORNECEDOR"],
        ]
    )

    rows = parse_xlsx_transactions(raw)

    assert len(rows) == 2
    assert rows[0].date == "2026-04-01"
    assert rows[0].description == "RECEBIMENTO CLIENTE"
    assert rows[0].amount == 1200.00
    assert rows[0].type == "inflow"
    assert rows[1].date == "2026-04-02"
    assert rows[1].description == "PAGAMENTO FORNECEDOR"
    assert rows[1].amount == -250.50
    assert rows[1].type == "outflow"


def test_parse_xlsx_transactions_raises_for_missing_required_columns() -> None:
    raw = _build_xlsx_bytes(
        [
            ["Data", "Descricao"],
            ["01/04/2026", "MERCADO"],
        ]
    )

    with pytest.raises(InvalidFileContentError):
        parse_xlsx_transactions(raw)

