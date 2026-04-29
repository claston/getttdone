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
