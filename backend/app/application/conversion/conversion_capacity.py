import logging
import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

_ResultT = TypeVar("_ResultT")


class ConversionCapacityLease:
    def __init__(self, *, controller: "ConversionCapacityController", source: str) -> None:
        self._controller = controller
        self._source = source
        self._acquired_at = monotonic()
        self._lock = Lock()
        self._released = False
        self._submitted = False

    @property
    def source(self) -> str:
        return self._source

    @property
    def acquired_at(self) -> float:
        return self._acquired_at

    def mark_submitted(self) -> None:
        with self._lock:
            if self._released:
                raise RuntimeError("Cannot submit a released conversion capacity lease.")
            if self._submitted:
                raise RuntimeError("Conversion capacity lease was already submitted.")
            self._submitted = True

    def release(self, *, outcome: str) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._controller._release(self, outcome=outcome)


class ConversionCapacityController(Generic[_ResultT]):
    def __init__(self, *, max_concurrency: int, retry_after_seconds: int) -> None:
        if not 1 <= max_concurrency <= 4:
            raise ValueError("CONVERSION_MAX_CONCURRENCY must be between 1 and 4.")
        if not 1 <= retry_after_seconds <= 300:
            raise ValueError("CONVERSION_BUSY_RETRY_AFTER_SECONDS must be between 1 and 300.")

        self.max_concurrency = max_concurrency
        self.retry_after_seconds = retry_after_seconds
        self._semaphore = BoundedSemaphore(max_concurrency)
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="conversion-worker",
        )
        self._state_lock = Lock()
        self._active_count = 0
        self._closed = False

    @classmethod
    def from_env(cls) -> "ConversionCapacityController":
        return cls(
            max_concurrency=_read_int_env("CONVERSION_MAX_CONCURRENCY", default=1),
            retry_after_seconds=_read_int_env("CONVERSION_BUSY_RETRY_AFTER_SECONDS", default=15),
        )

    @property
    def active_count(self) -> int:
        with self._state_lock:
            return self._active_count

    def try_acquire(self, *, source: str) -> ConversionCapacityLease | None:
        with self._state_lock:
            if self._closed:
                return None

        if not self._semaphore.acquire(blocking=False):
            logger.warning(
                "conversion_capacity_rejected source=%s active=%s max=%s retry_after_seconds=%s",
                source,
                self.active_count,
                self.max_concurrency,
                self.retry_after_seconds,
            )
            return None

        with self._state_lock:
            if self._closed:
                self._semaphore.release()
                return None
            self._active_count += 1
            active_count = self._active_count

        logger.info(
            "conversion_capacity_acquired source=%s active=%s max=%s",
            source,
            active_count,
            self.max_concurrency,
        )
        return ConversionCapacityLease(controller=self, source=source)

    def submit(self, lease: ConversionCapacityLease, work: Callable[[], _ResultT]) -> Future[_ResultT]:
        lease.mark_submitted()

        def execute_and_release() -> _ResultT:
            outcome = "completed"
            try:
                return work()
            except Exception:
                outcome = "failed"
                raise
            finally:
                lease.release(outcome=outcome)

        try:
            future = self._executor.submit(execute_and_release)
            future.add_done_callback(
                lambda completed: lease.release(outcome="cancelled_before_start") if completed.cancelled() else None
            )
            return future
        except Exception:
            lease.release(outcome="submit_failed")
            raise

    def _release(self, lease: ConversionCapacityLease, *, outcome: str) -> None:
        duration_seconds = max(0.0, monotonic() - lease.acquired_at)
        with self._state_lock:
            self._active_count = max(0, self._active_count - 1)
            active_count = self._active_count
        self._semaphore.release()
        logger.info(
            "conversion_capacity_released source=%s outcome=%s active=%s max=%s duration_seconds=%.3f",
            lease.source,
            outcome,
            active_count,
            self.max_concurrency,
            duration_seconds,
        )

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=False)


def _read_int_env(name: str, *, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
