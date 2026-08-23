import asyncio
import logging
from threading import Event, current_thread

import pytest
from fastapi.testclient import TestClient

from app.application.conversion.conversion_capacity import ConversionCapacityController
from app.dependencies import (
    get_access_control_service,
    get_conversion_capacity_controller,
    get_convert_document_use_case,
)
from app.main import app


def test_capacity_rejects_instead_of_queueing_when_all_slots_are_busy() -> None:
    controller = ConversionCapacityController(max_concurrency=1, retry_after_seconds=15)
    started = Event()
    finish = Event()

    lease = controller.try_acquire(source="first")
    assert lease is not None

    future = controller.submit(
        lease,
        lambda: (started.set(), finish.wait(timeout=2), current_thread().name)[-1],
    )
    assert started.wait(timeout=1)

    assert controller.try_acquire(source="second") is None
    assert controller.active_count == 1

    finish.set()
    assert future.result(timeout=1).startswith("conversion-")
    assert controller.active_count == 0
    controller.close()


def test_capacity_releases_slot_when_submitted_conversion_fails() -> None:
    controller = ConversionCapacityController(max_concurrency=1, retry_after_seconds=15)
    lease = controller.try_acquire(source="failure")
    assert lease is not None

    def fail() -> None:
        raise RuntimeError("conversion failed")

    future = controller.submit(lease, fail)
    with pytest.raises(RuntimeError, match="conversion failed"):
        future.result(timeout=1)

    replacement = controller.try_acquire(source="replacement")
    assert replacement is not None
    replacement.release(outcome="test_complete")
    controller.close()


def test_capacity_with_four_workers_accepts_four_and_rejects_the_fifth(caplog) -> None:
    controller = ConversionCapacityController(max_concurrency=4, retry_after_seconds=15)
    leases = [controller.try_acquire(source=f"accepted-{index}") for index in range(4)]

    assert all(lease is not None for lease in leases)
    assert controller.active_count == 4
    with caplog.at_level(logging.WARNING):
        assert controller.try_acquire(source="fifth") is None

    assert "conversion_capacity_rejected source=fifth active=4 max=4 retry_after_seconds=15" in caplog.text
    for lease in leases:
        assert lease is not None
        lease.release(outcome="test_complete")
    controller.close()


def test_capacity_from_env_accepts_up_to_four_workers(monkeypatch) -> None:
    monkeypatch.setenv("CONVERSION_MAX_CONCURRENCY", "4")
    monkeypatch.setenv("CONVERSION_BUSY_RETRY_AFTER_SECONDS", "9")

    controller = ConversionCapacityController.from_env()

    assert controller.max_concurrency == 4
    assert controller.retry_after_seconds == 9
    controller.close()

    monkeypatch.setenv("CONVERSION_MAX_CONCURRENCY", "5")
    with pytest.raises(ValueError, match="CONVERSION_MAX_CONCURRENCY"):
        ConversionCapacityController.from_env()


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/convert", {}),
        ("/api/conversions/upload", {"accept": "text/event-stream"}),
    ],
)
def test_busy_conversion_endpoint_returns_controlled_503_before_staging(
    path: str,
    headers: dict[str, str],
    monkeypatch,
) -> None:
    controller = ConversionCapacityController(max_concurrency=1, retry_after_seconds=15)
    occupied_lease = controller.try_acquire(source="occupied")
    assert occupied_lease is not None
    staging_called = False

    async def track_staging(_file):
        nonlocal staging_called
        staging_called = True
        raise AssertionError("busy request must not stage its upload")

    monkeypatch.setattr("app.routers.upload._stage_upload_to_temp_file", track_staging)
    app.dependency_overrides[get_conversion_capacity_controller] = lambda: controller
    app.dependency_overrides[get_convert_document_use_case] = lambda: object()
    app.dependency_overrides[get_access_control_service] = lambda: object()

    try:
        with TestClient(app) as client:
            response = client.post(
                path,
                headers=headers,
                files={"file": ("sample.pdf", b"%PDF data", "application/pdf")},
            )

        assert response.status_code == 503
        assert response.headers["retry-after"] == "15"
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {
            "detail": {
                "code": "conversion_capacity_exceeded",
                "message": "Estamos processando outros arquivos no momento. Aguarde alguns segundos e tente novamente.",
                "retryable": True,
                "retry_after_seconds": 15,
            }
        }
        assert staging_called is False
        assert controller.active_count == 1
    finally:
        app.dependency_overrides.clear()
        occupied_lease.release(outcome="test_complete")
        controller.close()


def test_awaiting_conversion_pool_does_not_block_event_loop() -> None:
    controller = ConversionCapacityController(max_concurrency=1, retry_after_seconds=15)

    async def exercise() -> bool:
        lease = controller.try_acquire(source="async")
        assert lease is not None
        finish = Event()
        future = controller.submit(lease, lambda: finish.wait(timeout=1))

        async def release_after_event_loop_turn() -> bool:
            await asyncio.sleep(0.01)
            finish.set()
            return True

        conversion_result, event_loop_progressed = await asyncio.gather(
            asyncio.wrap_future(future),
            release_after_event_loop_turn(),
        )
        return bool(conversion_result and event_loop_progressed)

    assert asyncio.run(exercise()) is True
    controller.close()
