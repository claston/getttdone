import sqlite3
from datetime import datetime, timedelta, timezone

from app.application.access_control import (
    ANONYMOUS_QUOTA_LIMIT,
    REGISTERED_QUOTA_LIMIT,
    AccessControlService,
)
from app.application.errors import FileTooLargeError, InvalidUserTokenError, QuotaExceededError


def test_anonymous_quota_blocks_4th_attempt(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )
    identity = service.resolve_identity(anonymous_fingerprint="anon-device-a", user_token=None)
    assert identity.identity_type == "anonymous"
    assert identity.quota_limit == ANONYMOUS_QUOTA_LIMIT

    assert service.get_remaining_quota(identity) == 3
    assert service.consume_quota(identity) == 2
    assert service.consume_quota(identity) == 1
    assert service.consume_quota(identity) == 0
    assert service.get_remaining_quota(identity) == 0

    try:
        service.consume_quota(identity)
        assert False, "Expected QuotaExceededError"
    except QuotaExceededError:
        assert True


def test_register_user_gets_10_quota_and_valid_token(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )

    registered = service.register_user(name="Erica", email="erica@example.com", password="strong-pass")
    identity = service.resolve_identity(anonymous_fingerprint=None, user_token=registered.token)

    assert identity.identity_type == "user"
    assert identity.quota_limit == REGISTERED_QUOTA_LIMIT
    assert service.get_remaining_quota(identity) == 10


def test_upload_larger_than_2mb_is_rejected(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )
    raw = b"a" * ((2 * 1024 * 1024) + 1)
    try:
        service.assert_upload_size(raw)
        assert False, "Expected FileTooLargeError"
    except FileTooLargeError:
        assert True


def test_invalid_token_is_rejected(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )
    try:
        service.resolve_identity(anonymous_fingerprint=None, user_token="invalid.token")
        assert False, "Expected InvalidUserTokenError"
    except InvalidUserTokenError:
        assert True


def test_custom_anonymous_quota_limit_is_applied(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
        anonymous_quota_limit=99,
    )

    identity = service.resolve_identity(anonymous_fingerprint="anon-device-b", user_token=None)
    assert identity.identity_type == "anonymous"
    assert identity.quota_limit == 99
    assert service.get_remaining_quota(identity) == 99


def test_anonymous_quota_resets_after_week_window(tmp_path) -> None:
    now_box = [datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)]
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
        now_provider=lambda: now_box[0],
    )
    identity = service.resolve_identity(anonymous_fingerprint="anon-device-weekly", user_token=None)

    assert service.consume_quota(identity) == 2
    assert service.consume_quota(identity) == 1
    assert service.consume_quota(identity) == 0
    try:
        service.consume_quota(identity)
        assert False, "Expected QuotaExceededError"
    except QuotaExceededError:
        assert True

    now_box[0] = now_box[0] + timedelta(days=8)
    assert service.get_remaining_quota(identity) == 3
    assert service.consume_quota(identity) == 2


def test_google_user_is_created_and_reused_by_provider_id(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )

    first = service.register_or_authenticate_google_user(
        provider_user_id="google-sub-1",
        email="erica@example.com",
        name="Erica",
    )
    second = service.register_or_authenticate_google_user(
        provider_user_id="google-sub-1",
        email="erica@example.com",
        name="Erica Souza",
    )

    assert first.user_id == second.user_id
    assert second.name == "Erica Souza"
    assert second.token


def test_google_oauth_state_can_be_consumed_once(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )
    state, verifier = service.create_google_oauth_state(next_path="/client-area.html", ttl_seconds=600)
    consumed = service.consume_google_oauth_state(state=state)
    consumed_again = service.consume_google_oauth_state(state=state)

    assert consumed is not None
    assert consumed["state"] == state
    assert consumed["code_verifier"] == verifier
    assert consumed["next_path"] == "/client-area.html"
    assert consumed_again is None


def test_public_plans_are_seeded_with_versions(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )

    plans = service.list_public_plans()
    codes = {str(item["code"]) for item in plans}
    assert {"essencial", "profissional", "escritorio"}.issubset(codes)
    assert all(int(item["version"]) >= 1 for item in plans)
    prices = {str(item["code"]): int(item["price_cents"]) for item in plans}
    assert prices["essencial"] == 2990
    assert prices["profissional"] == 3990
    assert prices["escritorio"] == 4990


def test_existing_plans_have_prices_backfilled_on_init(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    service = AccessControlService(
        state_file=state_file,
        token_secret="test-secret",
    )
    del service

    db_file = state_file.with_suffix(".db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE plan_versions SET price_cents = 990 WHERE code = 'essencial'")
        conn.execute("UPDATE plan_versions SET price_cents = 1990 WHERE code = 'profissional'")
        conn.execute("UPDATE plan_versions SET price_cents = 2990 WHERE code = 'escritorio'")
        conn.commit()

    reloaded = AccessControlService(
        state_file=state_file,
        token_secret="test-secret",
    )
    prices = {str(item["code"]): int(item["price_cents"]) for item in reloaded.list_public_plans()}
    assert prices["essencial"] == 2990
    assert prices["profissional"] == 3990
    assert prices["escritorio"] == 4990


def test_registered_user_can_use_pages_plan_quota(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )
    user = service.register_user(name="Erica", email="erica@example.com", password="strong-pass")
    service.activate_user_plan(user_id=user.user_id, plan_code="essencial")

    identity = service.resolve_identity(anonymous_fingerprint=None, user_token=user.token)
    assert identity.identity_type == "user"
    assert identity.quota_mode == "pages"
    assert identity.quota_limit == 150
    assert identity.plan_code == "essencial"

    service.ensure_quota_available(identity, required_units=10)
    remaining = service.consume_quota(identity, consumed_units=10)
    assert remaining == 140


def test_create_checkout_intent_persists_pending_order(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )

    intent = service.create_checkout_intent(
        plan_code="profissional",
        customer_name="Erica Souza",
        customer_email="erica@example.com",
        customer_whatsapp="+55 11 99999-1111",
        customer_document="123.456.789-00",
        customer_notes="Contato preferencial por WhatsApp",
    )
    assert str(intent["id"]).startswith("chk_")
    assert intent["status"] == "pending"
    assert intent["plan_code"] == "profissional"
    assert intent["price_cents"] == 3990
