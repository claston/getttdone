from __future__ import annotations

import hashlib
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from seo_contract import normalize_visible_text, parse_html_signals


class _RecordingRedirectHandler(HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.chain: list[dict[str, Any]] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - stdlib override
        self.chain.append(
            {
                "from_url": req.full_url,
                "status": int(code),
                "location": str(headers.get("Location") or newurl),
            }
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _route_url(base_url: str, path: str) -> str:
    normalized_base = str(base_url or "").rstrip("/")
    normalized_path = "/" + str(path or "").lstrip("/")
    return f"{normalized_base}{normalized_path}"


def _internal_links(*, page_url: str, hrefs: tuple[str, ...]) -> list[str]:
    page = urlparse(page_url)
    links: list[str] = []
    for href in hrefs:
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != page.netloc:
            continue
        normalized = parsed.path or "/"
        if parsed.query:
            normalized = f"{normalized}?{parsed.query}"
        if normalized not in links:
            links.append(normalized)
    return links


def _contract_drift(*, route: dict[str, Any], result: dict[str, Any], visible_text: str) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []

    expected_redirect_count = int(route.get("expected_redirect_count", 0))
    actual_redirect_count = len(result["redirect_chain"])
    if actual_redirect_count != expected_redirect_count:
        drift.append(
            {
                "field": "redirect_count",
                "expected": expected_redirect_count,
                "actual": actual_redirect_count,
            }
        )

    scalar_fields = ("status", "title", "description", "canonical", "robots")
    expected_field_names = {
        "status": "expected_status",
        "title": "title",
        "description": "description",
        "canonical": "canonical",
        "robots": "robots",
    }
    for result_field in scalar_fields:
        expected = route.get(expected_field_names[result_field])
        actual = result.get(result_field)
        if actual != expected:
            drift.append({"field": result_field, "expected": expected, "actual": actual})

    expected_h1 = [route["h1"]]
    if result["h1"] != expected_h1:
        drift.append({"field": "h1", "expected": expected_h1, "actual": result["h1"]})

    expected_json_ld_types = sorted(set(route.get("json_ld_types", [])))
    actual_json_ld_types = sorted(set(result["json_ld_types"]))
    if actual_json_ld_types != expected_json_ld_types:
        drift.append(
            {
                "field": "json_ld_types",
                "expected": expected_json_ld_types,
                "actual": actual_json_ld_types,
            }
        )

    normalized_visible_text = normalize_visible_text(visible_text)
    for marker in route.get("content_markers", []):
        if normalize_visible_text(marker) not in normalized_visible_text:
            drift.append({"field": "content_marker", "expected": marker, "actual": None})

    return drift


def capture_route(*, base_url: str, route: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    request_url = _route_url(base_url, route["path"])
    redirect_handler = _RecordingRedirectHandler()
    opener = build_opener(redirect_handler)
    request = Request(
        request_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "OFXSimples-SEOBaseline/1.0",
        },
    )

    started_at = time.perf_counter()
    try:
        response = opener.open(request, timeout=timeout_seconds)  # noqa: S310 - URL is an explicit CLI input
    except HTTPError as exc:
        response = exc
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)

    with response:
        body = response.read()
        status = int(response.status)
        final_url = str(response.geturl())
        content_type = str(response.headers.get("Content-Type") or "")
        charset = response.headers.get_content_charset() or "utf-8"
        html = body.decode(charset, errors="replace")
        signals = parse_html_signals(html)
        result: dict[str, Any] = {
            "path": route["path"],
            "request_url": request_url,
            "status": status,
            "final_url": final_url,
            "redirect_chain": redirect_handler.chain,
            "response_ms": elapsed_ms,
            "content_type": content_type,
            "cache_control": response.headers.get("Cache-Control"),
            "x_robots_tag": response.headers.get("X-Robots-Tag"),
            "html_bytes": len(body),
            "html_sha256": hashlib.sha256(body).hexdigest(),
            "title": signals.title,
            "description": signals.description,
            "canonical": signals.canonical,
            "robots": signals.robots,
            "h1": list(signals.h1),
            "json_ld_types": list(signals.json_ld_types),
            "internal_links": _internal_links(page_url=final_url, hrefs=signals.internal_links),
        }

    drift = _contract_drift(route=route, result=result, visible_text=signals.visible_text)
    result["contract_ok"] = not drift
    result["contract_drift"] = drift
    return result
