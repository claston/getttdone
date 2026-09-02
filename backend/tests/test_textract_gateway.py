import pytest

from app.application.errors import InvalidFileContentError
from app.application.textract_gateway import TextractGateway


class _FakeS3Client:
    def __init__(self) -> None:
        self.upload_calls = 0
        self.delete_calls = 0
        self.upload_keys: list[str] = []

    def upload_fileobj(self, fileobj, bucket: str, key: str) -> None:
        _ = fileobj
        _ = bucket
        self.upload_calls += 1
        self.upload_keys.append(key)

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        _ = Bucket
        _ = Key
        self.delete_calls += 1


class _FakeTextractClient:
    def __init__(self, *, fail: bool = False, start_error: Exception | None = None) -> None:
        self.fail = fail
        self.start_error = start_error
        self.poll_calls = 0
        self.fetch_calls = 0
        self.start_analysis_calls = 0
        self.start_text_calls = 0
        self.start_requests: list[dict[str, object]] = []

    def start_document_analysis(self, **kwargs):
        if self.start_error is not None:
            raise self.start_error
        self.start_analysis_calls += 1
        self.start_requests.append(kwargs)
        return {"JobId": "job-123"}

    def start_document_text_detection(self, **kwargs):
        if self.start_error is not None:
            raise self.start_error
        self.start_text_calls += 1
        self.start_requests.append(kwargs)
        return {"JobId": "job-123"}

    def get_document_analysis(self, **kwargs):
        _ = kwargs
        max_results = int(kwargs.get("MaxResults", 0) or 0)
        next_token = kwargs.get("NextToken")
        if max_results == 1:
            self.poll_calls += 1
            if self.fail:
                return {"JobStatus": "FAILED", "StatusMessage": "failed on provider"}
            return {"JobStatus": "SUCCEEDED"}

        self.fetch_calls += 1
        if next_token is None:
            return {
                "JobStatus": "SUCCEEDED",
                "DocumentMetadata": {"Pages": 2},
                "Blocks": [{"BlockType": "LINE", "Id": "l1", "Text": "a"}],
                "NextToken": "token-2",
            }
        return {
            "JobStatus": "SUCCEEDED",
            "DocumentMetadata": {"Pages": 2},
            "Blocks": [{"BlockType": "LINE", "Id": "l2", "Text": "b"}],
        }

    def get_document_text_detection(self, **kwargs):
        return self.get_document_analysis(**kwargs)


class _FakeSession:
    def __init__(self, *, s3: _FakeS3Client, textract: _FakeTextractClient) -> None:
        self._s3 = s3
        self._textract = textract

    def client(self, service_name: str):
        if service_name == "s3":
            return self._s3
        if service_name == "textract":
            return self._textract
        raise AssertionError("unexpected service")


class _FakeBoto3:
    def __init__(self, *, s3: _FakeS3Client, textract: _FakeTextractClient) -> None:
        self._s3 = s3
        self._textract = textract

        class _SessionFactory:
            def __init__(self, s3_client: _FakeS3Client, textract_client: _FakeTextractClient) -> None:
                self.s3_client = s3_client
                self.textract_client = textract_client

            def Session(self, region_name=None):
                _ = region_name
                return _FakeSession(s3=self.s3_client, textract=self.textract_client)

        self.session = _SessionFactory(self._s3, self._textract)


def test_gateway_fetches_paginated_blocks_and_deletes_s3_object(monkeypatch) -> None:
    s3 = _FakeS3Client()
    textract = _FakeTextractClient()
    fake_boto3 = _FakeBoto3(s3=s3, textract=textract)
    monkeypatch.setattr("app.application.textract_gateway._load_boto3", lambda: fake_boto3)

    gateway = TextractGateway(bucket="test-bucket", region="us-east-1", poll_interval_seconds=0.01, timeout_seconds=3.0)
    result = gateway.analyze_pdf(raw_bytes=b"%PDF synthetic")

    assert result["provider"] == "aws_textract"
    assert result["page_count"] == 2
    assert len(result["blocks"]) == 2
    assert s3.upload_calls == 1
    assert s3.delete_calls == 1
    assert textract.start_text_calls == 1
    assert textract.start_analysis_calls == 0
    assert result["metrics"]["textract_mode"] == "text"


def test_gateway_uses_analysis_mode_when_requested(monkeypatch) -> None:
    s3 = _FakeS3Client()
    textract = _FakeTextractClient()
    fake_boto3 = _FakeBoto3(s3=s3, textract=textract)
    monkeypatch.setattr("app.application.textract_gateway._load_boto3", lambda: fake_boto3)

    gateway = TextractGateway(
        bucket="test-bucket",
        region="us-east-1",
        poll_interval_seconds=0.01,
        timeout_seconds=3.0,
        mode="analysis",
    )
    result = gateway.analyze_pdf(raw_bytes=b"%PDF synthetic")

    assert result["provider"] == "aws_textract"
    assert textract.start_analysis_calls == 1
    assert textract.start_text_calls == 0
    assert result["metrics"]["textract_mode"] == "analysis"


def test_gateway_deletes_s3_object_even_when_textract_job_fails(monkeypatch) -> None:
    s3 = _FakeS3Client()
    textract = _FakeTextractClient(fail=True)
    fake_boto3 = _FakeBoto3(s3=s3, textract=textract)
    monkeypatch.setattr("app.application.textract_gateway._load_boto3", lambda: fake_boto3)

    gateway = TextractGateway(bucket="test-bucket", region="us-east-1", poll_interval_seconds=0.01, timeout_seconds=3.0)
    with pytest.raises(InvalidFileContentError):
        gateway.analyze_pdf(raw_bytes=b"%PDF synthetic")
    assert s3.upload_calls == 1
    assert s3.delete_calls == 1


def test_gateway_uses_stable_s3_key_and_client_request_token(monkeypatch) -> None:
    s3 = _FakeS3Client()
    textract = _FakeTextractClient()
    fake_boto3 = _FakeBoto3(s3=s3, textract=textract)
    monkeypatch.setattr("app.application.textract_gateway._load_boto3", lambda: fake_boto3)

    gateway = TextractGateway(bucket="test-bucket", region="us-east-1", poll_interval_seconds=0.01, timeout_seconds=3.0)
    gateway.analyze_pdf(raw_bytes=b"%PDF same document")
    gateway.analyze_pdf(raw_bytes=b"%PDF same document")

    assert s3.upload_keys[0] == s3.upload_keys[1]
    assert textract.start_requests[0]["ClientRequestToken"] == textract.start_requests[1]["ClientRequestToken"]
    assert len(str(textract.start_requests[0]["ClientRequestToken"])) == 64


def test_gateway_propagates_timeout_for_queue_retry(monkeypatch) -> None:
    s3 = _FakeS3Client()
    textract = _FakeTextractClient()
    fake_boto3 = _FakeBoto3(s3=s3, textract=textract)
    monkeypatch.setattr("app.application.textract_gateway._load_boto3", lambda: fake_boto3)
    monkeypatch.setattr(
        "app.application.textract_gateway._wait_for_job",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("Textract polling timeout.")),
    )

    gateway = TextractGateway(bucket="test-bucket", region="us-east-1", poll_interval_seconds=0.01, timeout_seconds=3.0)
    with pytest.raises(TimeoutError, match="Textract polling timeout"):
        gateway.analyze_pdf(raw_bytes=b"%PDF synthetic")


def test_gateway_maps_transient_provider_error_to_retryable_connection_error(monkeypatch) -> None:
    class _TransientProviderError(Exception):
        response = {"Error": {"Code": "ThrottlingException"}}

    s3 = _FakeS3Client()
    textract = _FakeTextractClient(start_error=_TransientProviderError("provider details must not escape"))
    fake_boto3 = _FakeBoto3(s3=s3, textract=textract)
    monkeypatch.setattr("app.application.textract_gateway._load_boto3", lambda: fake_boto3)

    gateway = TextractGateway(bucket="test-bucket", region="us-east-1", poll_interval_seconds=0.01, timeout_seconds=3.0)
    with pytest.raises(ConnectionError, match="temporarily unavailable") as exc:
        gateway.analyze_pdf(raw_bytes=b"%PDF synthetic")

    assert "provider details" not in str(exc.value)
