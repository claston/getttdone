from pathlib import Path

from fastapi.testclient import TestClient

from app.application import AccessControlService, ReportService, TempAnalysisStorage
from app.application.conversion.async_conversion_rollout import AsyncConversionRolloutPolicy
from app.application.conversion.conversion_runtime_config import ConversionRuntimeConfig
from app.application.models import AnalysisData, TransactionRow
from app.dependencies import (
    get_access_control_service,
    get_async_conversion_report_service,
    get_async_conversion_rollout_policy,
    get_conversion_runtime_config,
    get_report_service,
)
from app.main import app


def _analysis(analysis_id: str) -> AnalysisData:
    rows = [
        TransactionRow(
            date="2026-09-01",
            description="PIX TESTE",
            amount=25.0,
            category="Outros",
            reconciliation_status="unmatched",
        )
    ]
    return AnalysisData(
        analysis_id=analysis_id,
        file_type="pdf",
        upload_filename="canario.pdf",
        transactions_total=1,
        total_inflows=25.0,
        total_outflows=0.0,
        net_total=25.0,
        preview_transactions=rows,
        report_transactions=rows,
    )


def _build_services(tmp_path: Path, *, save_to_async: bool) -> tuple[TestClient, TempAnalysisStorage]:
    access_control = AccessControlService(
        state_file=tmp_path / "access-control.json",
        token_secret="test-secret",
    )
    user = access_control.register_user(name="Canary", email="a@a.com.br", password="strong-pass")
    legacy_storage = TempAnalysisStorage(root_dir=tmp_path / "legacy", ttl_seconds=3600)
    async_storage = TempAnalysisStorage(root_dir=tmp_path / "async", ttl_seconds=3600)
    target = async_storage if save_to_async else legacy_storage
    target.save_analysis(_analysis("an_canary"))
    target.set_convert_owner("an_canary", "user", user.user_id)

    app.dependency_overrides[get_access_control_service] = lambda: access_control
    app.dependency_overrides[get_report_service] = lambda: ReportService(storage=legacy_storage)
    app.dependency_overrides[get_async_conversion_report_service] = lambda: ReportService(storage=async_storage)
    app.dependency_overrides[get_conversion_runtime_config] = lambda: ConversionRuntimeConfig.from_mapping({})
    app.dependency_overrides[get_async_conversion_rollout_policy] = lambda: AsyncConversionRolloutPolicy.from_mapping(
        {"CONVERSION_ASYNC_USER_EMAIL_ALLOWLIST": "a@a.com.br"}
    )
    return TestClient(app), target


def test_allowlisted_user_downloads_report_from_async_storage(tmp_path: Path) -> None:
    client, _ = _build_services(tmp_path, save_to_async=True)
    access_control = app.dependency_overrides[get_access_control_service]()
    token = access_control.authenticate_user(email="a@a.com.br", password="strong-pass").token
    try:
        response = client.get(
            "/convert-report/an_canary?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        access_control.close()
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "PIX TESTE" in response.text


def test_allowlisted_user_report_lookup_falls_back_to_legacy_storage(tmp_path: Path) -> None:
    client, _ = _build_services(tmp_path, save_to_async=False)
    access_control = app.dependency_overrides[get_access_control_service]()
    token = access_control.authenticate_user(email="a@a.com.br", password="strong-pass").token
    try:
        response = client.get(
            "/convert-report/an_canary?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        access_control.close()
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "PIX TESTE" in response.text


def test_allowlisted_user_edits_analysis_in_async_storage(tmp_path: Path) -> None:
    client, async_storage = _build_services(tmp_path, save_to_async=True)
    access_control = app.dependency_overrides[get_access_control_service]()
    token = access_control.authenticate_user(email="a@a.com.br", password="strong-pass").token
    try:
        response = client.post(
            "/convert-edits/an_canary",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "edits": [
                    {
                        "row_id": "row_1",
                        "date": "2026-09-02",
                        "description": "PIX EDITADO",
                        "credit": 30.0,
                        "debit": None,
                    }
                ]
            },
        )
    finally:
        access_control.close()
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["preview_transactions"][0]["description"] == "PIX EDITADO"
    csv_path = async_storage.get_convert_report_path("an_canary", file_format="csv")
    assert "PIX EDITADO" in csv_path.read_text(encoding="utf-8")
