from __future__ import annotations

from pathlib import Path
import sys


SUSPICIOUS_TOKENS = (
    "Ã¡",
    "Ã¢",
    "Ã£",
    "Ã§",
    "Ã©",
    "Ãª",
    "Ã­",
    "Ã³",
    "Ã´",
    "Ãµ",
    "Ãº",
    "Ã‰",
    "Ã‡",
    "â€™",
    "â€œ",
    "â€",
    "â€“",
    "â€”",
    "â€¢",
    "âœ",
    "â",
    "Â©",
    "Â ",
    "�",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    frontend = root / "frontend"
    targets = sorted(list(frontend.glob("*.html")) + list(frontend.glob("*.js")))

    has_issues = False
    for file_path in targets:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            print(f"[encoding-error] {file_path}: {exc}")
            has_issues = True
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            if any(token in line for token in SUSPICIOUS_TOKENS):
                safe_line = line.strip().encode("unicode_escape").decode("ascii")
                print(f"[mojibake] {file_path}:{line_no}: {safe_line}")
                has_issues = True

    if has_issues:
        print("\nFound suspicious text encoding patterns in frontend files.")
        return 1

    print("OK: no suspicious mojibake patterns found in frontend .html/.js files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
