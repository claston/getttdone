import shutil
import sqlite3
from pathlib import Path
from tempfile import mkdtemp

from fastapi.testclient import TestClient

from app.application.access_control import AccessControlService
from app.application.contact_service import ContactDeliveryError, ContactDeliveryResult
from app.dependencies import get_access_control_service, get_contact_service
from app.main import app


class _InMemoryConnCtx:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _AccessControlServiceInMemory(AccessControlService):
    def __init__(self, **kwargs) -> None:
        self._test_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._test_conn.row_factory = sqlite3.Row
        super().__init__(**kwargs)

    def _connect(self) -> _InMemoryConnCtx:
        return _InMemoryConnCtx(self._test_conn)


class _FakeEmailService:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def send_text_email(self, *, to_email: str, subject: str, text: str, reply_to=None):
        self.messages.append({"to_email": to_email, "subject": subject, "text": text})
        return ContactDeliveryResult(delivery_mode="resend", provider_message_id=f"msg_{len(self.messages)}")


class _FailingEmailService:
    async def send_text_email(self, *, to_email: str, subject: str, text: str, reply_to=None):
        _ = (to_email, subject, text, reply_to)
        raise ContactDeliveryError("provider unavailable")


def _build_client(state_dir: Path):
    access_control = _AccessControlServiceInMemory(
        state_file=state_dir / "access-control-state.json",
        token_secret="test-secret",
        email_verification_required=True,
    )
    email_service = _FakeEmailService()
    app.dependency_overrides[get_access_control_service] = lambda: access_control
    app.dependency_overrides[get_contact_service] = lambda: email_service
    return TestClient(app), access_control, email_service


def test_local_registration_requires_email_confirmation_before_login(monkeypatch) -> None:
    state_dir = Path(mkdtemp(prefix="email-verification-api-"))
    client, _service, email_service = _build_client(state_dir)
    monkeypatch.setenv("AUTH_EMAIL_VERIFICATION_FRONTEND_URL", "https://www.ofxsimples.com.br/verificar-email.html")

    try:
        registered = client.post(
            "/auth/register",
            json={
                "name": "Erica",
                "email": "erica@example.com",
                "password": "strong-pass",
                "accepted_terms": True,
            },
        )
        assert registered.status_code == 200
        payload = registered.json()
        assert payload["verification_required"] is True
        assert payload["verification_status"] == "pending"
        assert payload["email_delivery_status"] == "sent"
        assert payload["user_token"] is None
        assert payload["quota_remaining"] == 0
        assert len(email_service.messages) == 1
        confirmation_url = email_service.messages[0]["text"].split("Confirme seu e-mail: ", 1)[1].splitlines()[0]
        assert "verificar-email.html#token=" in confirmation_url
        token = confirmation_url.split("#token=", 1)[1]

        blocked = client.post(
            "/auth/login",
            json={"email": "erica@example.com", "password": "strong-pass"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "email_verification_required"

        confirmed = client.post("/auth/email-verification/confirm", json={"token": token})
        assert confirmed.status_code == 200
        assert confirmed.json()["verification_status"] == "verified"

        login = client.post(
            "/auth/login",
            json={"email": "erica@example.com", "password": "strong-pass"},
        )
        assert login.status_code == 200
        assert login.json()["quota_remaining"] == 10

        reused = client.post("/auth/email-verification/confirm", json={"token": token})
        assert reused.status_code == 400
        assert reused.json()["detail"]["code"] == "invalid_or_expired_email_verification_token"
    finally:
        app.dependency_overrides.clear()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_email_verification_resend_is_generic_for_unknown_email() -> None:
    state_dir = Path(mkdtemp(prefix="email-verification-api-"))
    client, _service, email_service = _build_client(state_dir)

    try:
        response = client.post(
            "/auth/email-verification/resend",
            json={"email": "unknown@example.com"},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        assert email_service.messages == []
    finally:
        app.dependency_overrides.clear()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_registration_keeps_pending_account_recoverable_when_delivery_fails() -> None:
    state_dir = Path(mkdtemp(prefix="email-verification-api-"))
    client, service, _email_service = _build_client(state_dir)
    app.dependency_overrides[get_contact_service] = lambda: _FailingEmailService()

    try:
        response = client.post(
            "/auth/register",
            json={
                "name": "Erica",
                "email": "erica@example.com",
                "password": "strong-pass",
                "accepted_terms": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["verification_status"] == "pending"
        assert response.json()["email_delivery_status"] == "failed"
        with service._connect() as conn:
            row = service._fetchone(
                conn,
                "SELECT delivery_status FROM email_verification_tokens WHERE user_id = ?",
                (response.json()["user_id"],),
            )
        assert row is not None
        assert row["delivery_status"] == "failed"
    finally:
        app.dependency_overrides.clear()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_email_verification_frontend_assets_exist() -> None:
    frontend_root = Path(__file__).resolve().parents[2] / "frontend"
    html = (frontend_root / "verificar-email.html").read_text(encoding="utf-8")
    script = (frontend_root / "verificar-email.js").read_text(encoding="utf-8")

    assert "Confirme seu e-mail" in html
    assert "/auth/email-verification/confirm" in script
    assert "window.location.hash" in script
