from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.application.conversion.conversion_job_repository import ConversionJobStatus
from scripts.run_conversion_worker_canary import (
    CANARY_OBJECT_KEY,
    CANARY_STORAGE_KEY,
    AwsCliCanaryClient,
    build_canary_records,
    build_sqs_event,
    load_env_file,
    summarize_record,
)


def test_canary_uses_the_single_iam_reserved_pdf_object() -> None:
    assert CANARY_STORAGE_KEY == "doc_cafe5afe0000000000000000"
    assert CANARY_OBJECT_KEY == (
        "conversion/jobs/doc_cafe5afe0000000000000000/document.pdf"
    )


def test_build_canary_records_is_isolated_from_real_user_quota() -> None:
    raw_pdf = b"%PDF-1.7 synthetic scanned statement"

    batch, job = build_canary_records(raw_pdf=raw_pdf, run_id="abc123")

    assert batch.batch_id == "batch_worker_canary_abc123"
    assert batch.identity_type == "anonymous"
    assert batch.identity_id == "gettdone-worker-canary"
    assert batch.files_count == 1
    assert job.job_id == "job_worker_canary_abc123"
    assert job.batch_id == batch.batch_id
    assert job.identity.identity_type == "anonymous"
    assert job.identity.identity_id == "gettdone-worker-canary"
    assert job.identity.quota_limit == 1000
    assert job.preflight_result.scanned_likely is True
    assert job.preflight_result.estimated_pages_count == 1
    assert job.document.storage_key == CANARY_STORAGE_KEY
    assert job.document.filename == "worker-canary-synthetic-scanned.pdf"
    assert job.document.file_type == "pdf"
    assert job.document.size_bytes == len(raw_pdf)
    assert job.document.sha256_hex == hashlib.sha256(raw_pdf).hexdigest()


def test_build_sqs_event_matches_worker_contract_and_forces_a_terminal_attempt() -> None:
    event = build_sqs_event(
        job_id="job_worker_canary_abc123",
        batch_id="batch_worker_canary_abc123",
        trace_id="trace-worker-canary-abc123",
    )

    assert len(event["Records"]) == 1
    record = event["Records"][0]
    assert record["messageId"] == "worker-canary-abc123"
    assert record["attributes"]["ApproximateReceiveCount"] == "5"
    assert json.loads(record["body"]) == {
        "schema_version": 1,
        "event_type": "conversion.requested",
        "job_id": "job_worker_canary_abc123",
        "batch_id": "batch_worker_canary_abc123",
        "trace_id": "trace-worker-canary-abc123",
    }


def test_load_env_file_handles_comments_and_quoted_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# local secrets\n"
        'DATABASE_URL="postgresql://user:secret@host/db?sslmode=require"\n'
        "DATABASE_SCHEMA='gettdone'\n",
        encoding="utf-8",
    )

    values = load_env_file(env_path)

    assert values == {
        "DATABASE_URL": "postgresql://user:secret@host/db?sslmode=require",
        "DATABASE_SCHEMA": "gettdone",
    }


def test_upload_reserves_canary_object_without_bucket_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AwsCliCanaryClient(profile="gettdone-iac", region="us-east-1", aws_cli="aws")
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(*arguments: str, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, stdout="{}", stderr="")

    monkeypatch.setattr(client, "_run", fake_run)

    client.upload_pdf(bucket="synthetic-bucket", raw_pdf=b"%PDF synthetic", path=tmp_path / "input.pdf")

    put_arguments = calls[0][0]
    assert put_arguments[:2] == ("s3api", "put-object")
    assert put_arguments[put_arguments.index("--if-none-match") + 1] == "*"
    assert calls[1][0][:2] == ("s3api", "head-object")


def test_post_worker_object_check_accepts_s3_missing_key_403_without_list_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AwsCliCanaryClient(profile="gettdone-iac", region="us-east-1", aws_cli="aws")
    monkeypatch.setattr(
        client,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            255,
            stdout="",
            stderr="An error occurred (403) when calling the HeadObject operation: Forbidden",
        ),
    )

    assert client.reserved_object_remains(bucket="synthetic-bucket") is False


def test_summarize_completed_record_reports_textract_evidence() -> None:
    record = type(
        "Record",
        (),
        {
            "status": ConversionJobStatus.COMPLETED,
            "failure": None,
            "result": type(
                "Result",
                (),
                {
                    "analysis_id": "an_123",
                    "payload": {
                        "analysis": {
                            "pdf_processing_metrics": {
                                "textract_attempted": 1,
                                "textract_used": 1,
                                "extraction_provider": "aws_textract",
                            }
                        }
                    },
                },
            )(),
        },
    )()

    summary = summarize_record(record)

    assert summary == {
        "status": "completed",
        "analysis_id": "an_123",
        "failure_code": None,
        "textract_attempted": True,
        "textract_used": True,
        "extraction_provider": "aws_textract",
    }


def test_summarize_record_rejects_success_without_textract_evidence() -> None:
    record = type(
        "Record",
        (),
        {
            "status": ConversionJobStatus.COMPLETED,
            "failure": None,
            "result": type(
                "Result",
                (),
                {"analysis_id": "an_123", "payload": {"analysis": {}}},
            )(),
        },
    )()

    with pytest.raises(RuntimeError, match="Textract"):
        summarize_record(record)
