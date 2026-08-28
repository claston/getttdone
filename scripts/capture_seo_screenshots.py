from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "seo" / "protected-routes.json"
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture desktop and mobile screenshots for critical SEO routes.")
    parser.add_argument("--base-url", default="https://www.ofxsimples.com.br")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _route_slug(path: str) -> str:
    if path == "/":
        return "home"
    slug = path.strip("/").replace("/", "__")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", slug)
    return slug or "home"


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    routes = [route for route in manifest["routes"] if route.get("capture_screenshot")]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    captures: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for viewport_name, viewport in VIEWPORTS.items():
                context = browser.new_context(
                    viewport=viewport,
                    device_scale_factor=1,
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )
                try:
                    for route in routes:
                        page = context.new_page()
                        url = f"{str(args.base_url).rstrip('/')}{route['path']}"
                        response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=5_000)
                        except PlaywrightTimeoutError:
                            pass

                        filename = f"{_route_slug(route['path'])}--{viewport_name}.jpg"
                        screenshot_path = output_dir / filename
                        page.screenshot(path=str(screenshot_path), type="jpeg", quality=78, full_page=True)
                        captures.append(
                            {
                                "path": route["path"],
                                "viewport": viewport_name,
                                "width": viewport["width"],
                                "height": viewport["height"],
                                "status": response.status if response is not None else None,
                                "final_url": page.url,
                                "title": page.title(),
                                "file": filename,
                            }
                        )
                        print(f"[OK] {route['path']} ({viewport_name}) -> {filename}")
                        page.close()
                finally:
                    context.close()
        finally:
            browser.close()

    payload = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "base_url": str(args.base_url).rstrip("/"),
        "captures": captures,
    }
    (output_dir / "screenshots.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
