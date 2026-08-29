from dataclasses import dataclass

from app.application.access_control import IdentityContext
from app.application.conversion.conversion_batch_repository import InMemoryConversionBatchRepository
from app.application.conversion.conversion_batch_service import (
    ConversionBatchFile,
    ConversionBatchService,
)
from app.application.conversion.conversion_document_store import ConversionDocumentReference
from app.application.conversion.conversion_job_repository import ConversionJobStatus
from app.application.conversion.s3_direct_upload_service import PreparedS3Upload


class FakeDirectUploadService:
    def __init__(self) -> None:
        self.counter = 0
        self.verified: list[str] = []

    def prepare(self, *, filename, content_type, size_bytes, sha256_hex, max_size_bytes):
        self.counter += 1
        document = ConversionDocumentReference(
            storage_key=f"doc_{self.counter:024x}",
            filename=filename,
            file_type="pdf",
            size_bytes=size_bytes,
            sha256_hex=sha256_hex,
        )
        return self.prepare_reference(
            document=document,
            content_type=content_type,
            max_size_bytes=max_size_bytes,
        )

    def prepare_reference(self, *, document, content_type, max_size_bytes):
        return PreparedS3Upload(
            document=document,
            object_key=f"incoming/{document.storage_key}/document.pdf",
            upload_url="https://uploads.example.test",
            upload_fields={"key": document.storage_key, "Content-Type": content_type},
            expires_in_seconds=900,
        )

    def verify_uploaded(self, document):
        self.verified.append(document.storage_key)


@dataclass
class FakePublisher:
    calls: list[tuple[str, str, str]]

    def publish(self, *, job_id: str, batch_id: str, trace_id: str) -> str:
        self.calls.append((job_id, batch_id, trace_id))
        return f"message-{job_id}"


class FailOncePublisher(FakePublisher):
    def publish(self, *, job_id: str, batch_id: str, trace_id: str) -> str:
        if not self.calls:
            self.calls.append((job_id, batch_id, trace_id))
            raise TimeoutError("SQS temporarily unavailable")
        return super().publish(job_id=job_id, batch_id=batch_id, trace_id=trace_id)


def _files(count: int) -> list[ConversionBatchFile]:
    return [
        ConversionBatchFile(
            filename=f"extrato-{index}.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            sha256_hex=f"{index:064x}",
        )
        for index in range(1, count + 1)
    ]


def test_batch_service_prepares_twelve_independent_direct_uploads() -> None:
    repository = InMemoryConversionBatchRepository()
    uploads = FakeDirectUploadService()
    publisher = FakePublisher(calls=[])
    service = ConversionBatchService(repository=repository, direct_upload_service=uploads, queue_publisher=publisher)

    prepared = service.create(
        identity=IdentityContext(identity_type="user", identity_id="usr_123", quota_limit=20),
        files=_files(12),
        idempotency_key="request-123",
    )

    assert prepared.created is True
    assert prepared.snapshot.batch.files_count == 12
    assert len(prepared.uploads) == 12
    assert len({item.job_id for item in prepared.uploads}) == 12
    assert len({item.document.storage_key for item in prepared.uploads}) == 12


def test_batch_service_returns_fresh_urls_for_idempotent_retry() -> None:
    repository = InMemoryConversionBatchRepository()
    uploads = FakeDirectUploadService()
    service = ConversionBatchService(
        repository=repository,
        direct_upload_service=uploads,
        queue_publisher=FakePublisher(calls=[]),
    )
    identity = IdentityContext(identity_type="user", identity_id="usr_123", quota_limit=20)

    original = service.create(identity=identity, files=_files(2), idempotency_key="request-123")
    duplicate = service.create(identity=identity, files=_files(2), idempotency_key="request-123")

    assert duplicate.created is False
    assert duplicate.snapshot.batch.batch_id == original.snapshot.batch.batch_id
    assert [item.document for item in duplicate.uploads] == [item.document for item in original.uploads]


def test_batch_service_verifies_then_enqueues_each_uploaded_file() -> None:
    repository = InMemoryConversionBatchRepository()
    uploads = FakeDirectUploadService()
    publisher = FakePublisher(calls=[])
    service = ConversionBatchService(repository=repository, direct_upload_service=uploads, queue_publisher=publisher)
    identity = IdentityContext(identity_type="user", identity_id="usr_123", quota_limit=20)
    prepared = service.create(identity=identity, files=_files(2), idempotency_key="request-123")

    submitted = service.submit(
        batch_id=prepared.snapshot.batch.batch_id,
        identity=identity,
        trace_id="trace-123",
    )

    assert [item.status for item in submitted.jobs] == [ConversionJobStatus.QUEUED, ConversionJobStatus.QUEUED]
    assert len(uploads.verified) == 2
    assert [call[0] for call in publisher.calls] == [item.job.job_id for item in submitted.jobs]


def test_batch_service_submit_is_idempotent_after_jobs_are_queued() -> None:
    repository = InMemoryConversionBatchRepository()
    publisher = FakePublisher(calls=[])
    service = ConversionBatchService(
        repository=repository,
        direct_upload_service=FakeDirectUploadService(),
        queue_publisher=publisher,
    )
    identity = IdentityContext(identity_type="user", identity_id="usr_123", quota_limit=20)
    prepared = service.create(identity=identity, files=_files(2), idempotency_key="request-123")

    service.submit(batch_id=prepared.snapshot.batch.batch_id, identity=identity, trace_id="trace-123")
    service.submit(batch_id=prepared.snapshot.batch.batch_id, identity=identity, trace_id="trace-456")

    assert len(publisher.calls) == 2


def test_batch_service_replays_transactional_outbox_after_sqs_failure() -> None:
    repository = InMemoryConversionBatchRepository()
    publisher = FailOncePublisher(calls=[])
    service = ConversionBatchService(
        repository=repository,
        direct_upload_service=FakeDirectUploadService(),
        queue_publisher=publisher,
    )
    identity = IdentityContext(identity_type="user", identity_id="usr_123", quota_limit=20)
    prepared = service.create(identity=identity, files=_files(1), idempotency_key="request-123")

    try:
        service.submit(batch_id=prepared.snapshot.batch.batch_id, identity=identity, trace_id="trace-123")
        assert False, "Expected the first SQS publication to fail."
    except TimeoutError:
        pass

    assert repository.get(prepared.snapshot.jobs[0].job.job_id).status == ConversionJobStatus.QUEUED
    assert len(repository.list_pending_outbox()) == 1

    submitted = service.submit(
        batch_id=prepared.snapshot.batch.batch_id,
        identity=identity,
        trace_id="trace-456",
    )

    assert submitted.jobs[0].status == ConversionJobStatus.QUEUED
    assert repository.list_pending_outbox() == []
