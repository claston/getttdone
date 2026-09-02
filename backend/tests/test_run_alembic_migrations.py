from collections.abc import Callable, Iterator
from pathlib import Path

from scripts.run_alembic_migrations import run_migrations


def _runner(*return_codes: int) -> tuple[Callable[[], int], list[int]]:
    codes: Iterator[int] = iter(return_codes)
    calls: list[int] = []

    def run() -> int:
        calls.append(1)
        return next(codes)

    return run, calls


def test_migration_runner_stops_after_first_success() -> None:
    runner, calls = _runner(0)
    sleeps: list[int] = []

    result = run_migrations(runner=runner, sleeper=sleeps.append)

    assert result == 0
    assert len(calls) == 1
    assert sleeps == []


def test_migration_runner_retries_then_succeeds() -> None:
    runner, calls = _runner(9, 0)
    sleeps: list[int] = []

    result = run_migrations(runner=runner, sleeper=sleeps.append)

    assert result == 0
    assert len(calls) == 2
    assert sleeps == [5]


def test_migration_runner_propagates_last_failure() -> None:
    runner, calls = _runner(3, 7, 13)
    sleeps: list[int] = []

    result = run_migrations(runner=runner, sleeper=sleeps.append)

    assert result == 13
    assert len(calls) == 3
    assert sleeps == [5, 10]


def test_deploy_workflow_uses_failure_propagating_migration_runner() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / ".github" / "workflows" / "deploy-render-staging.yml").read_text(encoding="utf-8")

    assert "set -euo pipefail" in workflow
    assert "python scripts/run_alembic_migrations.py" in workflow
    assert "exit_code=$?" not in workflow
