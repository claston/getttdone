from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable


def _run_alembic_upgrade() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
    )
    return result.returncode


def run_migrations(
    *,
    max_attempts: int = 3,
    retry_delay_seconds: int = 5,
    runner: Callable[[], int] | None = None,
    sleeper: Callable[[int], None] = time.sleep,
) -> int:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds cannot be negative")

    run = runner or _run_alembic_upgrade
    last_exit_code = 1

    for attempt in range(1, max_attempts + 1):
        print(f"Running Alembic migration (attempt {attempt}/{max_attempts})...", flush=True)
        last_exit_code = run()
        if last_exit_code == 0:
            print("Alembic migration completed successfully.", flush=True)
            return 0

        if attempt == max_attempts:
            print(
                f"Alembic migration failed after {max_attempts} attempts (exit {last_exit_code}).",
                file=sys.stderr,
                flush=True,
            )
            return last_exit_code

        delay = attempt * retry_delay_seconds
        print(
            f"Alembic migration failed on attempt {attempt}/{max_attempts} "
            f"(exit {last_exit_code}). Retrying in {delay}s.",
            file=sys.stderr,
            flush=True,
        )
        sleeper(delay)

    return last_exit_code


def main() -> int:
    return run_migrations()


if __name__ == "__main__":
    raise SystemExit(main())
