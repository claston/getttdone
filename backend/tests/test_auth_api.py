from fastapi.testclient import TestClient

from app.application.access_control import AccessControlService
from app.dependencies import get_access_control_service
from app.main import app


def build_client(tmp_path) -> TestClient:
    access_control = AccessControlService(
        state_file=tmp_path / "access-control-state.json",
        token_secret="test-secret",
    )
    app.dependency_overrides[get_access_control_service] = lambda: access_control
    return TestClient(app)


def test_login_returns_user_token_and_registered_quota(tmp_path) -> None:
    client = build_client(tmp_path)

    register = client.post(
        "/auth/register",
        json={"name": "Erica", "email": "erica@example.com", "password": "strong-pass"},
    )
    assert register.status_code == 200

    response = client.post(
        "/auth/login",
        json={"email": "erica@example.com", "password": "strong-pass"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "erica@example.com"
    assert payload["name"] == "Erica"
    assert payload["user_token"]
    assert payload["quota_remaining"] == 10
    assert payload["quota_limit"] == 10
    app.dependency_overrides.clear()


def test_login_rejects_invalid_credentials(tmp_path) -> None:
    client = build_client(tmp_path)

    client.post(
        "/auth/register",
        json={"name": "Erica", "email": "erica@example.com", "password": "strong-pass"},
    )

    response = client.post(
        "/auth/login",
        json={"email": "erica@example.com", "password": "wrong-pass"},
    )

    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_auth_me_returns_user_profile_for_valid_token(tmp_path) -> None:
    client = build_client(tmp_path)

    register = client.post(
        "/auth/register",
        json={"name": "Erica", "email": "erica@example.com", "password": "strong-pass"},
    )
    token = register.json()["user_token"]

    response = client.get("/auth/me", params={"user_token": token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "erica@example.com"
    assert payload["name"] == "Erica"
    assert payload["quota_remaining"] == 10
    assert payload["quota_limit"] == 10
    app.dependency_overrides.clear()


def test_auth_me_rejects_invalid_token(tmp_path) -> None:
    client = build_client(tmp_path)

    response = client.get("/auth/me", params={"user_token": "invalid"})

    assert response.status_code == 401
    assert "Invalid user token" in response.json()["detail"]
    app.dependency_overrides.clear()
