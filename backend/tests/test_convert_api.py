from fastapi.testclient import TestClient

from app.dependencies import get_analyze_service
from app.main import app
from app.schemas import (
    AnalyzeResponse,
    BeforeAfterPreview,
    CategorySummary,
    Insight,
    OperationalSummary,
    ReconciliationSummary,
    TopExpense,
    TransactionPreview,
)


class FakeAnalyzeService:
    def analyze(self, filename: str, raw_bytes: bytes) -> AnalyzeResponse:
        return AnalyzeResponse(
            analysis_id="an_test123",
            file_type="pdf",
            transactions_total=1,
            total_inflows=100.0,
            total_outflows=-20.0,
            net_total=80.0,
            operational_summary=OperationalSummary(
                total_volume=120.0,
                inflow_count=1,
                outflow_count=1,
                reconciled_entries=0,
                unmatched_entries=1,
            ),
            reconciliation=ReconciliationSummary(
                matched_groups=0,
                reversed_entries=0,
                potential_duplicates=0,
            ),
            categories=[CategorySummary(category="Outros", total=-20.0, count=1)],
            top_expenses=[
                TopExpense(
                    description="TEST",
                    amount=-20.0,
                    date="2026-04-01",
                    category="Outros",
                )
            ],
            insights=[
                Insight(
                    type="test",
                    title="Test insight",
                    description=f"Bytes: {len(raw_bytes)}",
                )
            ],
            preview_transactions=[
                TransactionPreview(
                    date="2026-04-01",
                    description="TEST",
                    amount=-20.0,
                    category="Outros",
                    reconciliation_status="unmatched",
                )
            ],
            preview_before_after=[
                BeforeAfterPreview(
                    date="2026-04-01",
                    description_before="test",
                    description_after="TEST",
                    amount_before=-20.0,
                    amount_after=-20.0,
                )
            ],
            expires_at=None,
        )


def build_client() -> TestClient:
    app.dependency_overrides[get_analyze_service] = lambda: FakeAnalyzeService()
    return TestClient(app)


def test_convert_happy_path() -> None:
    client = build_client()
    response = client.post(
        "/convert",
        files={"file": ("sample.pdf", b"%PDF-1.4\n% test pdf", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_id"] == "an_test123"
    assert payload["mode"] == "convert"
    assert payload["quota_remaining"] is None
    assert payload["quota_limit"] is None
    assert payload["analysis"]["analysis_id"] == "an_test123"
    assert payload["analysis"]["file_type"] == "pdf"
    app.dependency_overrides.clear()


def test_convert_rejects_non_pdf() -> None:
    client = build_client()
    response = client.post(
        "/convert",
        files={"file": ("sample.csv", b"date,description,amount\n2026-04-01,TEST,-20.0", "text/csv")},
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_convert_rejects_file_larger_than_2mb() -> None:
    client = build_client()
    response = client.post(
        "/convert",
        files={"file": ("sample.pdf", b"%PDF-1.4\n" + (b"a" * (2 * 1024 * 1024 + 1)), "application/pdf")},
    )

    assert response.status_code == 400
    assert "2MB" in response.json()["detail"]
    app.dependency_overrides.clear()
