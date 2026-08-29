import pytest

from app.application.conversion.s3_direct_upload_service import S3DirectUploadService


class FakeS3Client:
    def __init__(self, *, head_response: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.head_response = head_response or {}

    def generate_presigned_post(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "url": "https://uploads.example.test/private-conversions",
            "fields": {**kwargs["Fields"], "key": kwargs["Key"], "policy": "signed"},
        }

    def head_object(self, **kwargs):
        self.calls.append(kwargs)
        return self.head_response


def test_direct_upload_uses_private_opaque_key_and_restrictive_post_policy() -> None:
    client = FakeS3Client()
    service = S3DirectUploadService(
        bucket="private-conversions",
        prefix="incoming",
        s3_client=client,
        storage_key_factory=lambda: "doc_0123456789abcdef01234567",
    )

    prepared = service.prepare(
        filename="extrato.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        sha256_hex="a" * 64,
        max_size_bytes=5 * 1024 * 1024,
    )

    assert prepared.document.storage_key == "doc_0123456789abcdef01234567"
    assert prepared.document.filename == "extrato.pdf"
    assert prepared.object_key == "incoming/doc_0123456789abcdef01234567/document.pdf"
    assert prepared.upload_url.startswith("https://")
    assert prepared.upload_fields["x-amz-meta-sha256"] == "a" * 64
    assert prepared.upload_fields["x-amz-server-side-encryption"] == "AES256"
    call = client.calls[0]
    assert ["content-length-range", 1, 5 * 1024 * 1024] in call["Conditions"]
    assert {"Content-Type": "application/pdf"} in call["Conditions"]
    assert call["ExpiresIn"] == 900
    assert "extrato.pdf" not in call["Key"]


@pytest.mark.parametrize(
    ("filename", "content_type", "size_bytes", "sha256_hex", "message"),
    [
        ("payload.exe", "application/octet-stream", 10, "a" * 64, "Unsupported"),
        ("extrato.pdf", "application/pdf", 0, "a" * 64, "size"),
        ("extrato.pdf", "application/pdf", 1025, "a" * 64, "size"),
        ("extrato.pdf", "application/pdf", 10, "not-a-digest", "SHA-256"),
        ("extrato.pdf", "text/plain", 10, "a" * 64, "content type"),
    ],
)
def test_direct_upload_rejects_metadata_that_could_bypass_worker_validation(
    filename: str,
    content_type: str,
    size_bytes: int,
    sha256_hex: str,
    message: str,
) -> None:
    service = S3DirectUploadService(
        bucket="private-conversions",
        s3_client=FakeS3Client(),
    )

    with pytest.raises(ValueError, match=message):
        service.prepare(
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256_hex=sha256_hex,
            max_size_bytes=1024,
        )


def test_direct_upload_supports_sse_kms_without_exposing_credentials() -> None:
    client = FakeS3Client()
    service = S3DirectUploadService(
        bucket="private-conversions",
        server_side_encryption="aws:kms",
        kms_key_id="alias/gettdone-conversions",
        s3_client=client,
    )

    prepared = service.prepare(
        filename="extrato.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256_hex="b" * 64,
        max_size_bytes=1024,
    )

    assert prepared.upload_fields["x-amz-server-side-encryption"] == "aws:kms"
    assert prepared.upload_fields["x-amz-server-side-encryption-aws-kms-key-id"] == "alias/gettdone-conversions"


def test_direct_upload_verifies_size_and_declared_digest_before_queueing() -> None:
    client = FakeS3Client(head_response={"ContentLength": 10, "Metadata": {"sha256": "b" * 64}})
    service = S3DirectUploadService(bucket="private-conversions", prefix="incoming", s3_client=client)
    prepared = service.prepare(
        filename="extrato.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256_hex="b" * 64,
        max_size_bytes=1024,
    )

    service.verify_uploaded(prepared.document)

    assert client.calls[-1] == {
        "Bucket": "private-conversions",
        "Key": f"incoming/{prepared.document.storage_key}/document.pdf",
    }


@pytest.mark.parametrize(
    "head_response",
    [
        {"ContentLength": 9, "Metadata": {"sha256": "b" * 64}},
        {"ContentLength": 10, "Metadata": {"sha256": "c" * 64}},
    ],
)
def test_direct_upload_rejects_tampered_object_before_queueing(head_response: dict) -> None:
    client = FakeS3Client(head_response=head_response)
    service = S3DirectUploadService(bucket="private-conversions", s3_client=client)
    prepared = service.prepare(
        filename="extrato.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256_hex="b" * 64,
        max_size_bytes=1024,
    )

    with pytest.raises(ValueError, match="does not match"):
        service.verify_uploaded(prepared.document)
