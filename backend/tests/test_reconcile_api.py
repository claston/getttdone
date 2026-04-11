from fastapi.testclient import TestClient

from app.main import app


def test_reconcile_happy_path_accepts_bank_and_sheet_files() -> None:
    client = TestClient(app)

    response = client.post(
        "/reconcile",
        files={
            "bank_file": ("bank.ofx", b"<OFX>...</OFX>", "application/octet-stream"),
            "sheet_file": ("sheet.csv", b"data,valor,descricao\n2026-04-01,100,TEST", "text/csv"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["bank_filename"] == "bank.ofx"
    assert payload["bank_file_type"] == "ofx"
    assert payload["sheet_filename"] == "sheet.csv"
    assert payload["sheet_file_type"] == "csv"


def test_reconcile_rejects_unsupported_bank_file_type() -> None:
    client = TestClient(app)

    response = client.post(
        "/reconcile",
        files={
            "bank_file": ("bank.pdf", b"%PDF", "application/pdf"),
            "sheet_file": ("sheet.xlsx", b"fake-xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported bank file type. Use CSV, XLSX, or OFX."


def test_reconcile_rejects_unsupported_sheet_file_type() -> None:
    client = TestClient(app)

    response = client.post(
        "/reconcile",
        files={
            "bank_file": ("bank.csv", b"date,description,amount\n2026-04-01,TEST,10", "text/csv"),
            "sheet_file": ("sheet.ofx", b"<OFX>...</OFX>", "application/octet-stream"),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported sheet file type. Use CSV or XLSX."
