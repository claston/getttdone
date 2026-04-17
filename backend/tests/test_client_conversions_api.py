from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.application import AccessControlService, ReportService, TempAnalysisStorage
from app.application.models import AnalysisData, TransactionRow
from app.dependencies import get_access_control_service, get_report_service
from app.main import app


def _build_analysis_data(analysis_id: str, filename: str, layout_name: str, created_at: datetime) -> AnalysisData:
    return AnalysisData(
        analysis_id=analysis_id,
        file_type="pdf",
        upload_filename=filename,
        transactions_total=1,
        total_inflows=100.0,
        total_outflows=-20.0,
        net_total=80.0,
        preview_transactions=[
            TransactionRow(
                date="2026-04-01",
                description="TEST",
                amount=-20.0,
                category="Outros",
                reconciliation_status="unmatched",
            )
        ],
        report_transactions=[
            TransactionRow(
                date="2026-04-01",
                description="TEST",
                amount=-20.0,
                category="Outros",
                reconciliation_status="unmatched",
            )
        ],
        updated_at=created_at.isoformat(),
        layout_inference_name=layout_name,
        layout_inference_confidence=0.95,
    )


def build_client(tmp_path: Path) -> tuple[TestClient, str, str]:
    current = {"now": datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)}
    storage = TempAnalysisStorage(
        root_dir=tmp_path,
        ttl_seconds=3600,
        now_provider=lambda: current["now"],
    )
    access_control = AccessControlService(
        state_file=tmp_path / "access-control-state.json",
        token_secret="test-secret",
    )

    user_a = access_control.register_user(name="Erica", email="erica@example.com", password="strong-pass")
    user_b = access_control.register_user(name="Clara", email="clara@example.com", password="strong-pass")

    identity_a = access_control.resolve_identity(anonymous_fingerprint=None, user_token=user_a.token)
    identity_b = access_control.resolve_identity(anonymous_fingerprint=None, user_token=user_b.token)

    storage.save_analysis(
        _build_analysis_data(
            analysis_id="an_old",
            filename="NU_150702837_01NOV2023_30NOV2023.pdf",
            layout_name="Nubank",
            created_at=current["now"],
        )
    )
    storage.set_convert_owner(
        analysis_id="an_old",
        identity_type=identity_a.identity_type,
        identity_id=identity_a.identity_id,
    )

    current["now"] = current["now"] + timedelta(minutes=5)
    storage.save_analysis(
        _build_analysis_data(
            analysis_id="an_new",
            filename="itau_extrato_032026.pdf",
            layout_name="Itau",
            created_at=current["now"],
        )
    )
    storage.set_convert_owner(
        analysis_id="an_new",
        identity_type=identity_a.identity_type,
        identity_id=identity_a.identity_id,
    )

    current["now"] = current["now"] + timedelta(minutes=1)
    storage.save_analysis(
        _build_analysis_data(
            analysis_id="an_other",
            filename="other_user.pdf",
            layout_name="Nubank",
            created_at=current["now"],
        )
    )
    storage.set_convert_owner(
        analysis_id="an_other",
        identity_type=identity_b.identity_type,
        identity_id=identity_b.identity_id,
    )

    app.dependency_overrides[get_report_service] = lambda: ReportService(storage=storage)
    app.dependency_overrides[get_access_control_service] = lambda: access_control
    return TestClient(app), user_a.token, user_b.token


def test_client_conversions_returns_only_owner_items_in_desc_order(tmp_path: Path) -> None:
    client, token_a, _token_b = build_client(tmp_path)

    response = client.get("/client/conversions", params={"user_token": token_a})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["items"][0]["processing_id"] == "an_new"
    assert payload["items"][0]["filename"] == "itau_extrato_032026.pdf"
    assert payload["items"][0]["model"] == "Itau"
    assert payload["items"][0]["conversion_type"] == "pdf-ofx"
    assert payload["items"][0]["status"] == "Sucesso"
    assert payload["items"][1]["processing_id"] == "an_old"
    app.dependency_overrides.clear()


def test_client_conversions_respects_limit_parameter(tmp_path: Path) -> None:
    client, token_a, _token_b = build_client(tmp_path)

    response = client.get("/client/conversions", params={"user_token": token_a, "limit": 1})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["processing_id"] == "an_new"
    app.dependency_overrides.clear()


def test_client_conversions_rejects_invalid_token(tmp_path: Path) -> None:
    client, _token_a, _token_b = build_client(tmp_path)

    response = client.get("/client/conversions", params={"user_token": "invalid-token"})

    assert response.status_code == 401
    assert "Invalid user token" in response.json()["detail"]
    app.dependency_overrides.clear()
