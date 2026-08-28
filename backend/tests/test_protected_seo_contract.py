from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from app.main import app
from seo_contract import normalize_visible_text, parse_html_signals

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "seo" / "protected-routes.json"
BASELINE_ROOT = REPO_ROOT / "seo" / "baseline" / "2026-08-28"

EXPECTED_PROTECTED_PATHS = {
    "/",
    "/blog/",
    "/blog/7-erros-comuns-na-conciliacao-bancaria/",
    "/blog/checklist-fechamento-financeiro-com-ofx/",
    "/blog/como-validar-ofx-antes-de-importar-no-erp/",
    "/blog/o-que-e-ofx-e-como-usar/",
    "/contato.html",
    "/convert.html",
    "/converter-pdf-para-excel.html",
    "/converter-pdf-para-ofx.html",
    "/ofx-convert.html",
    "/planos.html",
    "/politica-de-privacidade.html",
}


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def protected_routes() -> list[dict]:
    return load_manifest()["routes"]


def test_protected_seo_manifest_covers_all_reported_indexed_routes() -> None:
    assert MANIFEST_PATH.is_file(), "Create seo/protected-routes.json before changing indexed pages."

    manifest = load_manifest()
    routes = manifest.get("routes", [])
    paths = [route.get("path") for route in routes]

    assert manifest.get("schema_version") == 1
    assert manifest.get("site_origin") == "https://www.ofxsimples.com.br"
    assert len(paths) == len(set(paths)), "Protected SEO paths must be unique."
    assert set(paths) == EXPECTED_PROTECTED_PATHS


@pytest.mark.parametrize("route", protected_routes(), ids=lambda route: route["path"])
def test_protected_route_source_matches_semantic_contract(route: dict) -> None:
    frontend_root = (REPO_ROOT / "frontend").resolve()
    source_path = (REPO_ROOT / route["source_file"]).resolve()

    assert source_path.is_relative_to(frontend_root)
    assert source_path.is_file()

    html = source_path.read_bytes().decode("utf-8")
    signals = parse_html_signals(html)

    assert signals.title == route["title"]
    assert signals.description == route["description"]
    assert signals.canonical == route["canonical"]
    assert signals.robots == route["robots"]
    assert signals.h1 == (route["h1"],)
    assert set(signals.json_ld_types) == set(route["json_ld_types"])

    visible_text = normalize_visible_text(signals.visible_text)
    for marker in route["content_markers"]:
        assert normalize_visible_text(marker) in visible_text


@pytest.mark.parametrize("route", protected_routes(), ids=lambda route: route["path"])
def test_protected_route_is_served_without_redirect(route: dict) -> None:
    client = TestClient(app)

    response = client.get(route["path"], follow_redirects=False)

    assert response.status_code == route["expected_status"]
    assert "location" not in response.headers
    assert response.headers["content-type"].startswith("text/html")

    signals = parse_html_signals(response.text)
    assert signals.title == route["title"]
    assert signals.canonical == route["canonical"]
    assert signals.h1 == (route["h1"],)


def test_sitemap_matches_protected_route_indexing_contract() -> None:
    client = TestClient(app)

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    root = ElementTree.fromstring(response.text)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    sitemap_urls = {loc.text for loc in root.findall("sm:url/sm:loc", namespace)}
    site_origin = load_manifest()["site_origin"]

    for route in protected_routes():
        route_url = route["canonical"] or f"{site_origin}{route['path']}"
        if route["sitemap_expected"]:
            assert route_url in sitemap_urls
        else:
            assert route_url not in sitemap_urls


def test_legacy_converter_conflicting_indexing_signals_remain_explicit() -> None:
    legacy_route = next(route for route in protected_routes() if route["path"] == "/ofx-convert.html")
    robots_lines = set((REPO_ROOT / "frontend" / "robots.txt").read_text(encoding="utf-8").splitlines())

    assert legacy_route["robots"] == "noindex,follow"
    assert legacy_route["canonical"] is None
    assert legacy_route["sitemap_expected"] is False
    assert "Disallow: /ofx-convert.html" in robots_lines


def test_versioned_production_baseline_covers_every_protected_route() -> None:
    baseline_path = BASELINE_ROOT / "technical-production.json"
    assert baseline_path.is_file()

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    captured_routes = baseline["routes"]

    assert baseline["schema_version"] == 1
    assert baseline["base_url"] == "https://www.ofxsimples.com.br"
    assert baseline["contract_ok"] is True
    assert {route["path"] for route in captured_routes} == EXPECTED_PROTECTED_PATHS
    assert all(route["contract_ok"] for route in captured_routes)
    assert all(route["status"] == 200 for route in captured_routes)
    assert all(route["redirect_chain"] == [] for route in captured_routes)


def test_versioned_visual_baseline_covers_critical_routes_on_both_viewports() -> None:
    screenshot_root = BASELINE_ROOT / "screenshots"
    screenshot_index = json.loads((screenshot_root / "screenshots.json").read_text(encoding="utf-8"))
    critical_paths = {route["path"] for route in protected_routes() if route["capture_screenshot"]}
    captures = screenshot_index["captures"]

    assert screenshot_index["base_url"] == "https://www.ofxsimples.com.br"
    assert {(capture["path"], capture["viewport"]) for capture in captures} == {
        (path, viewport) for path in critical_paths for viewport in {"desktop", "mobile"}
    }
    assert all(capture["status"] == 200 for capture in captures)
    for capture in captures:
        screenshot_path = screenshot_root / capture["file"]
        assert screenshot_path.is_file()
        assert screenshot_path.stat().st_size > 10_000
