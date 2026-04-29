from fastapi.testclient import TestClient

from app.main import app


def test_security_headers_present_on_health_response(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_header_present_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
