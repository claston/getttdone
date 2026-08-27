import shutil
import sqlite3
from pathlib import Path
from tempfile import mkdtemp

import pytest
from fastapi.testclient import TestClient

from app.application.access_control import AccessControlService
from app.application.errors import InvalidUserTokenError
from app.dependencies import get_access_control_service
from app.main import app
from app.routers.access_control_common import ANONYMOUS_IDENTITY_COOKIE_NAME


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


def _build_client(state_dir: Path) -> tuple[TestClient, AccessControlService]:
    access_control = _AccessControlServiceInMemory(
        state_file=state_dir / "access-control-state.json",
        token_secret="test-secret",
    )
    app.dependency_overrides[get_access_control_service] = lambda: access_control
    return TestClient(app), access_control


def test_anonymous_identity_cookie_token_is_signed_and_rejects_tampering(tmp_path) -> None:
    service = AccessControlService(
        state_file=tmp_path / "state.json",
        token_secret="test-secret",
    )
    fingerprint = "afp_server-generated"

    token = service.issue_anonymous_identity_token(fingerprint=fingerprint)

    assert service.decode_anonymous_identity_token(token=token) == fingerprint
    with pytest.raises(InvalidUserTokenError):
        service.decode_anonymous_identity_token(token=f"{token[:-1]}x")


def test_anonymous_session_migrates_existing_identity_and_preserves_quota() -> None:
    state_dir = Path(mkdtemp(prefix="anonymous-session-api-"))
    client, service = _build_client(state_dir)
    legacy_fingerprint = "anon-1787846400000-a1b2c3d4"
    try:
        legacy_identity = service.resolve_identity(
            anonymous_fingerprint=legacy_fingerprint,
            user_token=None,
        )
        service.consume_quota(legacy_identity, consumed_units=2)

        response = client.post(
            "/auth/anonymous-session",
            json={"legacy_fingerprint": legacy_fingerprint},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        assert response.headers["cache-control"] == "no-store"
        cookie_token = response.cookies.get(ANONYMOUS_IDENTITY_COOKIE_NAME)
        assert cookie_token
        assert service.decode_anonymous_identity_token(token=cookie_token) == legacy_fingerprint
        assert "HttpOnly" in response.headers["set-cookie"]

        resumed = client.post("/auth/anonymous-session", json={})
        assert resumed.status_code == 200
        resumed_cookie_token = resumed.cookies.get(ANONYMOUS_IDENTITY_COOKIE_NAME)
        assert resumed_cookie_token
        resumed_fingerprint = service.decode_anonymous_identity_token(token=resumed_cookie_token)
        resumed_identity = service.resolve_identity(
            anonymous_fingerprint=resumed_fingerprint,
            user_token=None,
        )
        assert resumed_identity.identity_id == legacy_identity.identity_id
        assert service.get_remaining_quota(resumed_identity) == 1
    finally:
        app.dependency_overrides.clear()
        service.close()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_anonymous_session_does_not_trust_unknown_legacy_fingerprint() -> None:
    state_dir = Path(mkdtemp(prefix="anonymous-session-api-"))
    client, service = _build_client(state_dir)
    unknown_legacy_fingerprint = "anon-1787846400000-deadbeef"
    try:
        response = client.post(
            "/auth/anonymous-session",
            json={"legacy_fingerprint": unknown_legacy_fingerprint},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        cookie_token = response.cookies.get(ANONYMOUS_IDENTITY_COOKIE_NAME)
        assert cookie_token
        server_fingerprint = service.decode_anonymous_identity_token(token=cookie_token)
        assert server_fingerprint.startswith("afp_")
        assert server_fingerprint != unknown_legacy_fingerprint
        assert not service.anonymous_identity_exists(fingerprint=server_fingerprint)
    finally:
        app.dependency_overrides.clear()
        service.close()
        shutil.rmtree(state_dir, ignore_errors=True)
