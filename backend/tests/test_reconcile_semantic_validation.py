from fastapi.testclient import TestClient

from app.main import app


def test_reconcile_rejects_bank_statement_uploaded_as_sheet() -> None:
    client = TestClient(app)
    bank_csv = (
        "date,description,amount\n"
        "2026-04-01,PIX TRANSF RECEBIDA AGENCIA 123 CONTA 456,100.00\n"
        "2026-04-02,TARIFA PACOTE SERVICOS,-12.34\n"
    )
    sheet_csv = (
        "date,description,amount\n"
        "2026-04-01,PIX TRANSF RECEBIDA AGENCIA 123 CONTA 456,100.00\n"
        "2026-04-02,TARIFA PACOTE SERVICOS,-12.34\n"
    )

    response = client.post(
        "/reconcile",
        files={
            "bank_file": ("bank.csv", bank_csv.encode("utf-8"), "text/csv"),
            "sheet_file": ("sheet.csv", sheet_csv.encode("utf-8"), "text/csv"),
        },
    )

    assert response.status_code == 422
    assert "bank statement" in response.json()["detail"].lower()
