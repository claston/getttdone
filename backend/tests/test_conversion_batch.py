from datetime import datetime, timezone

import pytest

from app.application.conversion.conversion_batch import (
    MAX_CONVERSION_BATCH_FILES,
    ConversionBatch,
    ConversionBatchStatus,
    resolve_conversion_batch_status,
)
from app.application.conversion.conversion_job_repository import ConversionJobStatus


def test_conversion_batch_creates_opaque_identity_owned_aggregate() -> None:
    created_at = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

    batch = ConversionBatch.create(
        identity_type="user",
        identity_id="usr_123",
        files_count=12,
        idempotency_key="request-123",
        created_at=created_at,
    )

    assert batch.batch_id.startswith("batch_")
    assert batch.identity_type == "user"
    assert batch.identity_id == "usr_123"
    assert batch.files_count == 12
    assert batch.idempotency_key == "request-123"
    assert batch.status == ConversionBatchStatus.UPLOADING
    assert batch.created_at == created_at


@pytest.mark.parametrize("files_count", [0, MAX_CONVERSION_BATCH_FILES + 1])
def test_conversion_batch_rejects_file_count_outside_supported_range(files_count: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 12"):
        ConversionBatch.create(
            identity_type="anonymous",
            identity_id="anon_123",
            files_count=files_count,
            idempotency_key="request-123",
        )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([ConversionJobStatus.UPLOADING, ConversionJobStatus.UPLOADED], ConversionBatchStatus.UPLOADING),
        ([ConversionJobStatus.QUEUED, ConversionJobStatus.SUBMITTED], ConversionBatchStatus.QUEUED),
        ([ConversionJobStatus.COMPLETED, ConversionJobStatus.QUEUED], ConversionBatchStatus.PROCESSING),
        ([ConversionJobStatus.RUNNING, ConversionJobStatus.QUEUED], ConversionBatchStatus.PROCESSING),
        ([ConversionJobStatus.RETRYING, ConversionJobStatus.COMPLETED], ConversionBatchStatus.PROCESSING),
        ([ConversionJobStatus.COMPLETED, ConversionJobStatus.COMPLETED], ConversionBatchStatus.COMPLETED),
        ([ConversionJobStatus.COMPLETED, ConversionJobStatus.FAILED], ConversionBatchStatus.COMPLETED_WITH_ERRORS),
        ([ConversionJobStatus.COMPLETED, ConversionJobStatus.EXPIRED], ConversionBatchStatus.COMPLETED_WITH_ERRORS),
        ([ConversionJobStatus.FAILED, ConversionJobStatus.EXPIRED], ConversionBatchStatus.FAILED),
    ],
)
def test_conversion_batch_status_is_derived_from_independent_jobs(
    statuses: list[ConversionJobStatus],
    expected: ConversionBatchStatus,
) -> None:
    assert resolve_conversion_batch_status(statuses) == expected


def test_conversion_batch_status_requires_at_least_one_job() -> None:
    with pytest.raises(ValueError, match="at least one job"):
        resolve_conversion_batch_status([])
