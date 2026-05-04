import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.application import ContactDeliveryError, ContactDeliveryResult, ContactProviderNotConfiguredError
from app.application.access_control import AccessControlService
from app.dependencies import get_access_control_service, get_contact_service
from app.main import app


class FakeContactService:
    def __init__(self) -> None:
        self.support_email = "suporte@ofxsimples.com"
        self.sent_emails: list[dict[str, str]] = []
        self._next_error: Exception | None = None

    def fail_with(self, error: Exception) -> None:
        self._next_error = error

    async def send_text_email(
        self,
        *,
        to_email: str,
        subject: str,
        text: str,
        reply_to: str | None = None,
    ) -> ContactDeliveryResult:
        if self._next_error is not None:
            raise self._next_error
        self.sent_emails.append(
            {
                "to_email": to_email,
                "subject": subject,
                "text": text,
                "reply_to": reply_to or "",
            }
        )
        return ContactDeliveryResult(delivery_mode="dry_run")


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


def build_client(fake_contact: FakeContactService) -> tuple[TestClient, AccessControlService]:
    access_control = _AccessControlServiceInMemory(
        state_file=Path("backend/tmp/checkout-access-control-state.json"),
        token_secret="test-secret",
    )
    app.dependency_overrides[get_access_control_service] = lambda: access_control
    app.dependency_overrides[get_contact_service] = lambda: fake_contact
    return TestClient(app), access_control


def test_checkout_creates_intent_and_sends_admin_and_customer_emails() -> None:
    fake_contact = FakeContactService()
    client, _service = build_client(fake_contact)

    try:
        response = client.post(
            "/checkout/intents",
            json={
                "plan_code": "profissional",
                "name": "Erica Souza",
                "email": "erica@example.com",
                "whatsapp": "+55 11 99999-1111",
                "document": "123.456.789-00",
                "notes": "Pode me chamar no whatsapp",
                "accepted_terms": True,
            },
        )
        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "pending"
        assert payload["plan_code"] == "profissional"
        assert payload["price_cents"] == 3990
        assert payload["admin_delivery_mode"] == "dry_run"
        assert payload["customer_delivery_mode"] == "dry_run"
        assert payload["intent_id"].startswith("chk_")
        assert len(fake_contact.sent_emails) == 2
        assert fake_contact.sent_emails[0]["to_email"] == "suporte@ofxsimples.com"
        assert fake_contact.sent_emails[1]["to_email"] == "erica@example.com"
    finally:
        app.dependency_overrides.clear()


def test_checkout_requires_terms_acceptance() -> None:
    fake_contact = FakeContactService()
    client, _service = build_client(fake_contact)

    try:
        response = client.post(
            "/checkout/intents",
            json={
                "plan_code": "essencial",
                "name": "Erica Souza",
                "email": "erica@example.com",
                "whatsapp": "+55 11 99999-1111",
                "accepted_terms": False,
            },
        )
        assert response.status_code == 400
        assert "terms" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_checkout_rejects_unknown_plan_code() -> None:
    fake_contact = FakeContactService()
    client, _service = build_client(fake_contact)

    try:
        response = client.post(
            "/checkout/intents",
            json={
                "plan_code": "premium",
                "name": "Erica Souza",
                "email": "erica@example.com",
                "whatsapp": "+55 11 99999-1111",
                "accepted_terms": True,
            },
        )
        assert response.status_code == 400
        assert "plan" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_checkout_returns_503_when_contact_provider_not_configured() -> None:
    fake_contact = FakeContactService()
    fake_contact.fail_with(ContactProviderNotConfiguredError())
    client, _service = build_client(fake_contact)

    try:
        response = client.post(
            "/checkout/intents",
            json={
                "plan_code": "essencial",
                "name": "Erica Souza",
                "email": "erica@example.com",
                "whatsapp": "+55 11 99999-1111",
                "accepted_terms": True,
            },
        )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_checkout_returns_502_when_contact_provider_fails() -> None:
    fake_contact = FakeContactService()
    fake_contact.fail_with(ContactDeliveryError("provider timeout"))
    client, _service = build_client(fake_contact)

    try:
        response = client.post(
            "/checkout/intents",
            json={
                "plan_code": "essencial",
                "name": "Erica Souza",
                "email": "erica@example.com",
                "whatsapp": "+55 11 99999-1111",
                "accepted_terms": True,
            },
        )
        assert response.status_code == 502
        assert "failed" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
