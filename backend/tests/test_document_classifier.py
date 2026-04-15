from io import BytesIO

from openpyxl import Workbook

from app.application.document_classifier import classify_document


def _build_xlsx_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_classify_bank_statement_csv() -> None:
    raw = (
        "date,description,amount\n"
        "2026-04-01,PIX TRANSF RECEBIDA AGENCIA 123 CONTA 456,100.00\n"
        "2026-04-02,TARIFA PACOTE SERVICOS,-12.34\n"
        "2026-04-03,ESTORNO TRANSFERENCIA,-50.00\n"
    ).encode("utf-8")

    result = classify_document("extrato_bancario.csv", raw)

    assert result.semantic_type == "extrato_bancario"
    assert result.confidence >= 0.6
    assert result.evidence


def test_classify_cash_flow_csv() -> None:
    raw = (
        "data,descricao,saldo inicial,saldo final,previsto,realizado\n"
        "2026-04-01,Movimento mensal,1000.00,1200.00,1100.00,1200.00\n"
        "2026-04-02,Movimento mensal,1200.00,900.00,1000.00,900.00\n"
    ).encode("utf-8")

    result = classify_document("fluxo_caixa.csv", raw)

    assert result.semantic_type == "fluxo_caixa"
    assert result.confidence >= 0.5
    assert result.evidence


def test_classify_accounting_sheet_xlsx() -> None:
    raw = _build_xlsx_bytes(
        [
            ["data", "historico", "conta_debito", "conta_credito", "debito", "credito"],
            ["2026-04-01", "Venda consultoria", "1.1.1 Caixa", "3.1.1 Receita", "", 1000.00],
            ["2026-04-02", "Pagamento fornecedor", "2.1.1 Despesa", "1.1.1 Caixa", 250.00, ""],
        ]
    )

    result = classify_document("planilha_contabil_formatada.xlsx", raw)

    assert result.semantic_type == "planilha_contabil_debito_credito"
    assert result.confidence >= 0.5
    assert result.evidence
