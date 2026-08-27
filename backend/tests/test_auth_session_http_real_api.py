from __future__ import annotations

import socket
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn

from app.application import AccessControlService
from app.dependencies import get_access_control_service
from app.main import app
from app.routers.auth import SESSION_ACCESS_COOKIE_NAME, SESSION_REFRESH_COOKIE_NAME


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


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _run_http_server(*, admin_emails: set[str] | None = None):
    access_control = _AccessControlServiceInMemory(
        state_file=Path("access-control-state.json"),
        token_secret="test-secret",
        admin_emails=admin_emails,
    )
    app.dependency_overrides[get_access_control_service] = lambda: access_control

    host = "127.0.0.1"
    port = _find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://{host}:{port}"
    with httpx.Client(timeout=2.0) as client:
        deadline = time.time() + 15.0
        while time.time() < deadline:
            try:
                response = client.get(f"{base_url}/health")
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            server.should_exit = True
            thread.join(timeout=5.0)
            app.dependency_overrides.clear()
            raise RuntimeError("HTTP test server did not start in time")

    try:
        yield base_url, access_control
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
        app.dependency_overrides.clear()


def test_http_auth_session_login_sets_cookies_and_me_works_without_bearer() -> None:
    with _run_http_server() as (base_url, access_control):
        with httpx.Client(timeout=5.0) as client:
            register = client.post(
                f"{base_url}/auth/register",
                json={
                    "name": "Erica",
                    "email": "erica@example.com",
                    "password": "strong-pass",
                    "accepted_terms": True,
                },
            )
            assert register.status_code == 200

            login = client.post(
                f"{base_url}/auth/session/login",
                json={"email": "erica@example.com", "password": "strong-pass"},
            )
            assert login.status_code == 200
            assert client.cookies.get(SESSION_ACCESS_COOKIE_NAME)
            assert client.cookies.get(SESSION_REFRESH_COOKIE_NAME)

            me = client.get(f"{base_url}/auth/me")

        events = access_control.list_user_login_events_for_admin(user_id=register.json()["user_id"])

    assert me.status_code == 200
    assert me.json()["email"] == "erica@example.com"
    assert len(events) == 2
    assert events[0]["auth_method"] == "local_password"


def test_http_auth_session_refresh_rotates_cookie_and_detects_reuse() -> None:
    with _run_http_server() as (base_url, access_control):
        with httpx.Client(timeout=5.0) as client:
            register = client.post(
                f"{base_url}/auth/register",
                json={
                    "name": "Erica",
                    "email": "erica@example.com",
                    "password": "strong-pass",
                    "accepted_terms": True,
                },
            )
            assert register.status_code == 200

            login = client.post(
                f"{base_url}/auth/session/login",
                json={"email": "erica@example.com", "password": "strong-pass"},
            )
            assert login.status_code == 200
            old_refresh = client.cookies.get(SESSION_REFRESH_COOKIE_NAME)
            assert old_refresh

            refreshed = client.post(f"{base_url}/auth/session/refresh")
            assert refreshed.status_code == 200
            new_refresh = client.cookies.get(SESSION_REFRESH_COOKIE_NAME)
            assert new_refresh
            assert new_refresh != old_refresh
            events = access_control.list_user_login_events_for_admin(user_id=register.json()["user_id"])
            assert len(events) == 2

            client.cookies.set(SESSION_REFRESH_COOKIE_NAME, old_refresh, path="/auth/session/refresh")
            reuse = client.post(f"{base_url}/auth/session/refresh")
            assert reuse.status_code == 401

    assert "reuse" in str(reuse.json().get("detail", "")).lower()


def test_http_auth_session_logout_revokes_session_cookie() -> None:
    with _run_http_server() as (base_url, _access_control):
        with httpx.Client(timeout=5.0) as client:
            register = client.post(
                f"{base_url}/auth/register",
                json={
                    "name": "Erica",
                    "email": "erica@example.com",
                    "password": "strong-pass",
                    "accepted_terms": True,
                },
            )
            assert register.status_code == 200

            login = client.post(
                f"{base_url}/auth/session/login",
                json={"email": "erica@example.com", "password": "strong-pass"},
            )
            assert login.status_code == 200

            logout = client.post(f"{base_url}/auth/session/logout")
            assert logout.status_code == 200

            me = client.get(f"{base_url}/auth/me")

    assert me.status_code == 401


def test_http_admin_deactivation_blocks_user_login() -> None:
    with _run_http_server(admin_emails={"admin@example.com"}) as (base_url, _access_control):
        with httpx.Client(timeout=5.0) as admin_client:
            admin = admin_client.post(
                f"{base_url}/auth/register",
                json={
                    "name": "Admin",
                    "email": "admin@example.com",
                    "password": "admin-pass",
                    "accepted_terms": True,
                },
            )
            assert admin.status_code == 200
            user = admin_client.post(
                f"{base_url}/auth/register",
                json={
                    "name": "Erica",
                    "email": "erica@example.com",
                    "password": "strong-pass",
                    "accepted_terms": True,
                },
            )
            assert user.status_code == 200

            admin_login = admin_client.post(
                f"{base_url}/admin/auth/login",
                json={"email": "admin@example.com", "password": "admin-pass"},
            )
            assert admin_login.status_code == 200

            deactivate = admin_client.post(
                f"{base_url}/admin/users/status",
                json={"user_id": user.json()["user_id"], "is_active": False},
            )
            assert deactivate.status_code == 200
            assert deactivate.json()["is_active"] is False

        with httpx.Client(timeout=5.0) as user_client:
            blocked_login = user_client.post(
                f"{base_url}/auth/session/login",
                json={"email": "erica@example.com", "password": "strong-pass"},
            )

    assert blocked_login.status_code == 401
