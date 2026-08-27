import pytest

from app.security_baseline import (
    parse_cors_allow_origins,
    read_bool_env,
    validate_production_security_baseline,
)


def test_validate_baseline_is_noop_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ACCESS_CONTROL_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    monkeypatch.delenv("UNLIMITED_ANON_QUOTA", raising=False)

    validate_production_security_baseline()


def test_validate_baseline_rejects_insecure_production_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ACCESS_CONTROL_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    monkeypatch.setenv("UNLIMITED_ANON_QUOTA", "true")

    with pytest.raises(RuntimeError) as exc:
        validate_production_security_baseline()

    message = str(exc.value)
    assert "ACCESS_CONTROL_TOKEN_SECRET must be configured in production." in message
    assert "CORS_ALLOW_ORIGINS must be configured in production." in message
    assert "ENABLE_API_DOCS must be false in production." in message
    assert "UNLIMITED_ANON_QUOTA must be false in production." in message


def test_validate_baseline_accepts_secure_production_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ACCESS_CONTROL_TOKEN_SECRET", "a" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://ofxsimples.com,https://app.ofxsimples.com")
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    monkeypatch.setenv("UNLIMITED_ANON_QUOTA", "false")

    validate_production_security_baseline()


def test_read_bool_env_falls_back_to_default_for_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_FLAG", "not-a-bool")
    assert read_bool_env("SECURITY_FLAG", default=False) is False
    assert read_bool_env("SECURITY_FLAG", default=True) is True


def test_parse_cors_allow_origins_ignores_empty_entries() -> None:
    origins = parse_cors_allow_origins(" https://a.com, ,https://b.com ,,")
    assert origins == ["https://a.com", "https://b.com"]


def test_validate_baseline_rejects_wildcard_cors_origin_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ACCESS_CONTROL_TOKEN_SECRET", "a" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    monkeypatch.setenv("UNLIMITED_ANON_QUOTA", "false")

    with pytest.raises(RuntimeError) as exc:
        validate_production_security_baseline()

    assert "CORS_ALLOW_ORIGINS cannot include wildcard '*'" in str(exc.value)


def test_validate_baseline_rejects_non_http_cors_origin_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ACCESS_CONTROL_TOKEN_SECRET", "a" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "ftp://bad-origin.example")
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    monkeypatch.setenv("UNLIMITED_ANON_QUOTA", "false")

    with pytest.raises(RuntimeError) as exc:
        validate_production_security_baseline()

    assert "must use http:// or https://" in str(exc.value)


def test_validate_baseline_requires_real_email_provider_when_verification_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ACCESS_CONTROL_TOKEN_SECRET", "a" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://www.ofxsimples.com.br")
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    monkeypatch.setenv("UNLIMITED_ANON_QUOTA", "false")
    monkeypatch.setenv("AUTH_EMAIL_VERIFICATION_REQUIRED", "true")
    monkeypatch.setenv("CONTACT_RESEND_DRY_RUN", "true")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("AUTH_EMAIL_VERIFICATION_FRONTEND_URL", "http://localhost/verificar-email.html")

    with pytest.raises(RuntimeError) as exc:
        validate_production_security_baseline()

    message = str(exc.value)
    assert "RESEND_API_KEY must be configured" in message
    assert "CONTACT_RESEND_DRY_RUN must be false" in message
    assert "AUTH_EMAIL_VERIFICATION_FRONTEND_URL must use HTTPS" in message


def test_validate_baseline_requires_smtp_credentials_for_hostinger_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ACCESS_CONTROL_TOKEN_SECRET", "a" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://www.ofxsimples.com.br")
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    monkeypatch.setenv("UNLIMITED_ANON_QUOTA", "false")
    monkeypatch.setenv("CONTACT_DELIVERY_PROVIDER", "hostinger_smtp")
    monkeypatch.setenv("CONTACT_SMTP_DRY_RUN", "true")
    monkeypatch.delenv("CONTACT_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("CONTACT_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("CONTACT_TO_EMAIL", raising=False)

    with pytest.raises(RuntimeError) as exc:
        validate_production_security_baseline()

    message = str(exc.value)
    assert "CONTACT_SMTP_USERNAME must be configured" in message
    assert "CONTACT_SMTP_PASSWORD must be configured" in message
    assert "CONTACT_TO_EMAIL must be configured" in message
    assert "CONTACT_SMTP_DRY_RUN must be false" in message


def test_validate_baseline_accepts_hostinger_smtp_contact_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ACCESS_CONTROL_TOKEN_SECRET", "a" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://www.ofxsimples.com.br")
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    monkeypatch.setenv("UNLIMITED_ANON_QUOTA", "false")
    monkeypatch.setenv("CONTACT_DELIVERY_PROVIDER", "hostinger_smtp")
    monkeypatch.setenv("CONTACT_SMTP_DRY_RUN", "false")
    monkeypatch.setenv("CONTACT_SMTP_USERNAME", "contato@ofxsimples.com.br")
    monkeypatch.setenv("CONTACT_SMTP_PASSWORD", "smtp-secret")
    monkeypatch.setenv("CONTACT_TO_EMAIL", "contato@ofxsimples.com.br")

    validate_production_security_baseline()
