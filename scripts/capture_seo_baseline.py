from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from seo_baseline import capture_route  # noqa: E402


DEFAULT_MANIFEST_PATH = REPO_ROOT / "seo" / "protected-routes.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture the technical SEO baseline for protected public routes.")
    parser.add_argument("--base-url", default="https://www.ofxsimples.com.br")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--fail-on-drift", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    captured_routes: list[dict] = []

    for route in manifest["routes"]:
        try:
            result = capture_route(
                base_url=args.base_url,
                route=route,
                timeout_seconds=max(1.0, float(args.timeout_seconds)),
            )
        except (OSError, TimeoutError, URLError) as exc:
            result = {
                "path": route["path"],
                "request_url": f"{str(args.base_url).rstrip('/')}{route['path']}",
                "contract_ok": False,
                "contract_drift": [
                    {
                        "field": "capture_error",
                        "expected": None,
                        "actual": f"{type(exc).__name__}: {exc}",
                    }
                ],
            }
        captured_routes.append(result)
        state = "OK" if result["contract_ok"] else "DRIFT"
        print(f"[{state}] {route['path']}")

    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "schema_version": 1,
        "captured_at_utc": captured_at,
        "base_url": str(args.base_url).rstrip("/"),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "indexed_routes_reported_at": manifest["indexed_routes_reported_at"],
        "contract_ok": all(route["contract_ok"] for route in captured_routes),
        "routes": captured_routes,
    }

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline written to {output_path}")

    if args.fail_on_drift and not payload["contract_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
