import asyncio
import smtplib
from email.message import EmailMessage

import pytest

from app import dependencies
from app.application import (
    ContactAttachment,
    ContactDeliveryError,
    ContactMessage,
    ContactProviderNotConfiguredError,
    ContactService,
    SmtpContactService,
)


class _FakeSmtpClient:
    def __init__(self) -> None:
        self.login_calls: list[tuple[str, str]] = []
        self.messages: list[EmailMessage] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))

    def send_message(self, message: EmailMessage) -> None:
        self.messages.append(message)


def _message(*, attachment: ContactAttachment | None = None) -> ContactMessage:
    return ContactMessage(
        name="Erica",
        email="erica@example.com",
        subject="Arquivo rejeitado",
        message="Não consegui converter.",
        attachment=attachment,
    )


def test_smtp_contact_delivers_to_hostinger_mailbox_with_reply_to_and_attachment(monkeypatch) -> None:
    smtp_client = _FakeSmtpClient()
    smtp_connections: list[tuple[str, int, float]] = []

    def fake_smtp_ssl(host: str, port: int, *, timeout: float, context):
        assert context is not None
        smtp_connections.append((host, port, timeout))
        return smtp_client

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_smtp_ssl)
    service = SmtpContactService(
        host="smtp.hostinger.com",
        port=465,
        username="contato@ofxsimples.com.br",
        password="smtp-secret",
        from_email="contato@ofxsimples.com.br",
        to_email="contato@ofxsimples.com.br",
        dry_run=False,
    )

    result = asyncio.run(
        service.deliver(
            _message(
                attachment=ContactAttachment(
                    filename="extrato.pdf",
                    content_type="application/pdf",
                    raw_bytes=b"%PDF test",
                )
            )
        )
    )

    assert result.delivery_mode == "hostinger_smtp"
    assert result.provider_message_id is None
    assert smtp_connections == [("smtp.hostinger.com", 465, 10.0)]
    assert smtp_client.login_calls == [("contato@ofxsimples.com.br", "smtp-secret")]
    assert len(smtp_client.messages) == 1
    sent = smtp_client.messages[0]
    assert sent["From"] == "contato@ofxsimples.com.br"
    assert sent["To"] == "contato@ofxsimples.com.br"
    assert sent["Reply-To"] == "erica@example.com"
    assert sent["Subject"] == "[Contato] Arquivo rejeitado"
    attachment = next(sent.iter_attachments())
    assert attachment.get_filename() == "extrato.pdf"
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_payload(decode=True) == b"%PDF test"


def test_smtp_contact_requires_credentials_when_not_in_dry_run() -> None:
    service = SmtpContactService(
        host="smtp.hostinger.com",
        port=465,
        username="",
        password="",
        from_email="contato@ofxsimples.com.br",
        to_email="contato@ofxsimples.com.br",
        dry_run=False,
    )

    with pytest.raises(ContactProviderNotConfiguredError):
        asyncio.run(service.deliver(_message()))


def test_smtp_contact_maps_provider_failure(monkeypatch) -> None:
    def failing_smtp_ssl(host: str, port: int, *, timeout: float, context):
        _ = (host, port, timeout, context)
        raise smtplib.SMTPConnectError(421, "provider unavailable")

    monkeypatch.setattr(smtplib, "SMTP_SSL", failing_smtp_ssl)
    service = SmtpContactService(
        host="smtp.hostinger.com",
        port=465,
        username="contato@ofxsimples.com.br",
        password="smtp-secret",
        from_email="contato@ofxsimples.com.br",
        to_email="contato@ofxsimples.com.br",
        dry_run=False,
    )

    with pytest.raises(ContactDeliveryError, match="SMTP provider"):
        asyncio.run(service.deliver(_message()))


def test_smtp_contact_from_env_uses_hostinger_defaults(monkeypatch) -> None:
    monkeypatch.setenv("CONTACT_SMTP_USERNAME", "contato@ofxsimples.com.br")
    monkeypatch.setenv("CONTACT_SMTP_PASSWORD", "smtp-secret")
    monkeypatch.setenv("CONTACT_SMTP_DRY_RUN", "false")
    monkeypatch.delenv("CONTACT_SMTP_HOST", raising=False)
    monkeypatch.delenv("CONTACT_SMTP_PORT", raising=False)
    monkeypatch.delenv("CONTACT_SMTP_FROM_EMAIL", raising=False)
    monkeypatch.delenv("CONTACT_TO_EMAIL", raising=False)

    service = SmtpContactService.from_env()

    assert service.support_email == "contato@ofxsimples.com.br"
    assert service._host == "smtp.hostinger.com"
    assert service._port == 465
    assert service._from_email == "contato@ofxsimples.com.br"
    assert service._dry_run is False


def test_contact_form_provider_is_separate_from_transactional_resend(monkeypatch) -> None:
    monkeypatch.setenv("CONTACT_DELIVERY_PROVIDER", "hostinger_smtp")
    monkeypatch.setenv("CONTACT_SMTP_USERNAME", "contato@ofxsimples.com.br")
    monkeypatch.setenv("CONTACT_SMTP_PASSWORD", "smtp-secret")
    monkeypatch.setenv("RESEND_API_KEY", "resend-secret")
    dependencies._contact_form_service = None
    dependencies._contact_service = None

    try:
        assert isinstance(dependencies.get_contact_form_service(), SmtpContactService)
        assert isinstance(dependencies.get_contact_service(), ContactService)
    finally:
        dependencies._contact_form_service = None
        dependencies._contact_service = None
