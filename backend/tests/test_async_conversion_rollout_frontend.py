from pathlib import Path

FRONTEND_SOURCE = Path(__file__).resolve().parents[2] / "frontend" / "ofx-convert.js"


def test_runtime_discovery_sends_optional_authenticated_user_header() -> None:
    source = FRONTEND_SOURCE.read_text(encoding="utf-8")
    runtime_block = source[source.index("async function syncConversionRuntime()") : source.index("function getUserToken()")]

    assert "buildOptionalAuthHeaders(getUserToken())" in runtime_block
    assert "headers: runtimeHeaders" in runtime_block
