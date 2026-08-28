from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from seo_baseline import capture_route

PAGE_HTML = b"""<!doctype html>
<html lang="pt-BR">
  <head>
    <title>Baseline test</title>
    <meta name="description" content="Technical baseline fixture" />
    <link rel="canonical" href="http://example.test/page" />
  </head>
  <body>
    <h1>Baseline heading</h1>
    <a href="/next">Next page</a>
  </body>
</html>
"""


class _BaselineFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        if self.path == "/page":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE_HTML)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib handler API
        return


def test_capture_route_records_redirects_and_html_signals() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BaselineFixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        route = {
            "path": "/redirect",
            "expected_status": 200,
            "expected_redirect_count": 1,
            "title": "Baseline test",
            "description": "Technical baseline fixture",
            "canonical": "http://example.test/page",
            "robots": None,
            "h1": "Baseline heading",
            "json_ld_types": [],
            "content_markers": ["Baseline heading"],
        }

        result = capture_route(base_url=base_url, route=route, timeout_seconds=3.0)

        assert result["status"] == 200
        assert result["final_url"] == f"{base_url}/page"
        assert result["redirect_chain"] == [
            {
                "from_url": f"{base_url}/redirect",
                "status": 302,
                "location": "/page",
            }
        ]
        assert result["title"] == "Baseline test"
        assert result["h1"] == ["Baseline heading"]
        assert result["internal_links"] == ["/next"]
        assert result["html_bytes"] == len(PAGE_HTML)
        assert len(result["html_sha256"]) == 64
        assert result["contract_ok"] is True
        assert result["contract_drift"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_capture_route_reports_semantic_contract_drift() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BaselineFixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        route = {
            "path": "/page",
            "expected_status": 200,
            "title": "Changed title",
            "description": "Technical baseline fixture",
            "canonical": "http://example.test/page",
            "robots": None,
            "h1": "Baseline heading",
            "json_ld_types": [],
            "content_markers": ["Missing marker"],
        }

        result = capture_route(base_url=f"http://127.0.0.1:{port}", route=route, timeout_seconds=3.0)

        assert result["contract_ok"] is False
        assert result["contract_drift"] == [
            {"field": "title", "expected": "Changed title", "actual": "Baseline test"},
            {"field": "content_marker", "expected": "Missing marker", "actual": None},
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
