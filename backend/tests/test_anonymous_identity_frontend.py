from pathlib import Path

FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"


def test_anonymous_frontends_migrate_legacy_storage_without_creating_new_fingerprints() -> None:
    for filename in ("index.js", "ofx-convert.js"):
        source = (FRONTEND_ROOT / filename).read_text(encoding="utf-8")

        assert "/auth/anonymous-session" in source
        assert 'localStorage.getItem(ANON_FINGERPRINT_KEY)' in source
        assert 'localStorage.removeItem(ANON_FINGERPRINT_KEY)' in source
        assert "localStorage.setItem(ANON_FINGERPRINT_KEY" not in source
        assert "Math.random().toString(16)" not in source
        assert "anonymous_fingerprint" not in source


def test_anonymous_frontend_requests_include_server_cookie_credentials() -> None:
    index_source = (FRONTEND_ROOT / "index.js").read_text(encoding="utf-8")
    convert_source = (FRONTEND_ROOT / "ofx-convert.js").read_text(encoding="utf-8")

    assert 'fetch(`${apiBase}/reconcile`, {' in index_source
    assert 'credentials: "include"' in index_source
    assert 'fetch(`${apiBase}/api/conversions/upload`, {' in convert_source
    assert 'credentials: "include"' in convert_source
