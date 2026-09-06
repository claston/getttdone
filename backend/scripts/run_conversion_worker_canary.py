from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.application.access_control import IdentityContext  # noqa: E402
from app.application.conversion.conversion_batch import (  # noqa: E402
    ConversionBatch,
    ConversionBatchStatus,
)
from app.application.conversion.conversion_document_store import (  # noqa: E402
    ConversionDocumentReference,
)
from app.application.conversion.conversion_job import ConversionJob  # noqa: E402
from app.application.conversion.conversion_job_repository import (  # noqa: E402
    ConversionJobStatus,
)
from app.application.conversion.postgres_conversion_batch_repository import (  # noqa: E402
    PostgresConversionBatchRepository,
)
from synthetic_pdf_corpus.catalog import load_scenario  # noqa: E402
from synthetic_pdf_corpus.generator import generate_pdf  # noqa: E402

CANARY_STORAGE_KEY = "doc_cafe5afe0000000000000000"
CANARY_OBJECT_KEY = f"conversion/jobs/{CANARY_STORAGE_KEY}/document.pdf"
CANARY_IDENTITY_ID = "gettdone-worker-canary"
CANARY_QUOTA_LIMIT = 1000
CANARY_SCENARIO = "inline_signed_values"
_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RUN_ID_PATTERN = re.compile(r"^[a-z0-9]{1,32}$")


@dataclass(frozen=True, slots=True)
class CanarySettings:
    database_url: str
    database_schema: str
    profile: str
    region: str
    foundation_stack: str
    worker_stack: str
    function_name: str


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def build_canary_records(*, raw_pdf: bytes, run_id: str) -> tuple[ConversionBatch, ConversionJob]:
    normalized_run_id = _normalize_run_id(run_id)
    batch_id = f"batch_worker_canary_{normalized_run_id}"
    job_id = f"job_worker_canary_{normalized_run_id}"
    identity = IdentityContext(
        identity_type="anonymous",
        identity_id=CANARY_IDENTITY_ID,
        quota_limit=CANARY_QUOTA_LIMIT,
    )
    document = ConversionDocumentReference(
        storage_key=CANARY_STORAGE_KEY,
        filename="worker-canary-synthetic-scanned.pdf",
        file_type="pdf",
        size_bytes=len(raw_pdf),
        sha256_hex=hashlib.sha256(raw_pdf).hexdigest(),
    )
    batch = ConversionBatch(
        batch_id=batch_id,
        identity_type=identity.identity_type,
        identity_id=identity.identity_id,
        files_count=1,
        idempotency_key=job_id,
        status=ConversionBatchStatus.UPLOADING,
        created_at=datetime.now(timezone.utc),
    )
    job = ConversionJob.create(
        document=document,
        identity=identity,
        scanned_likely=True,
        estimated_pages_count=1,
        job_id=job_id,
        idempotency_key=job_id,
        batch_id=batch_id,
    )
    return batch, job


def build_sqs_event(*, job_id: str, batch_id: str, trace_id: str) -> dict[str, object]:
    suffix = job_id.removeprefix("job_worker_canary_")
    body = {
        "schema_version": 1,
        "event_type": "conversion.requested",
        "job_id": job_id,
        "batch_id": batch_id,
        "trace_id": trace_id,
    }
    return {
        "Records": [
            {
                "messageId": f"worker-canary-{suffix}",
                "body": json.dumps(body, separators=(",", ":"), sort_keys=True),
                # The canary is a single synchronous invocation. Using the configured
                # terminal receive count avoids leaving a retrying production row.
                "attributes": {"ApproximateReceiveCount": "5"},
            }
        ]
    }


def summarize_record(record) -> dict[str, object]:
    status = record.status.value
    failure_code = record.failure.code if record.failure is not None else None
    analysis_id = record.result.analysis_id if record.result is not None else None
    metrics: dict[str, Any] = {}
    if record.result is not None and isinstance(record.result.payload, dict):
        analysis = record.result.payload.get("analysis")
        if isinstance(analysis, dict):
            raw_metrics = analysis.get("pdf_processing_metrics")
            if isinstance(raw_metrics, dict):
                metrics = raw_metrics
    summary = {
        "status": status,
        "analysis_id": analysis_id,
        "failure_code": failure_code,
        "textract_attempted": bool(int(metrics.get("textract_attempted", 0) or 0)),
        "textract_used": bool(int(metrics.get("textract_used", 0) or 0)),
        "extraction_provider": str(metrics.get("extraction_provider") or "").strip() or None,
    }
    if record.status == ConversionJobStatus.COMPLETED and not (
        summary["textract_attempted"]
        and summary["textract_used"]
        and summary["extraction_provider"] == "aws_textract"
    ):
        raise RuntimeError("Worker completed without the expected AWS Textract evidence.")
    return summary


class AwsCliCanaryClient:
    def __init__(self, *, profile: str, region: str, aws_cli: str | None = None) -> None:
        self.profile = profile
        self.region = region
        self.aws_cli = aws_cli or shutil.which("aws") or shutil.which("aws.exe") or ""
        if not self.aws_cli:
            raise RuntimeError("AWS CLI v2 was not found in PATH.")

    def assert_expected_identity(self) -> str:
        payload = self._run_json("sts", "get-caller-identity")
        arn = str(payload.get("Arn") or "")
        if ":assumed-role/GettDoneIaCOperator/" not in arn:
            raise RuntimeError("The canary must run with the GettDoneIaCOperator assumed role.")
        return arn

    def stack_outputs(self, stack_name: str) -> dict[str, str]:
        payload = self._run_json("cloudformation", "describe-stacks", "--stack-name", stack_name)
        stacks = payload.get("Stacks") if isinstance(payload, dict) else None
        if not isinstance(stacks, list) or len(stacks) != 1:
            raise RuntimeError(f"Unable to resolve CloudFormation stack {stack_name}.")
        outputs = stacks[0].get("Outputs") if isinstance(stacks[0], dict) else None
        if not isinstance(outputs, list):
            return {}
        return {
            str(item.get("OutputKey") or ""): str(item.get("OutputValue") or "")
            for item in outputs
            if isinstance(item, dict)
        }

    def assert_worker_dark_mode(self, worker_stack: str) -> None:
        outputs = self.stack_outputs(worker_stack)
        queue_enabled = outputs.get("QueueTriggerEnabled", "").strip().lower()
        dispatcher_enabled = outputs.get("OutboxDispatcherEnabled", "").strip().lower()
        if queue_enabled != "false" or dispatcher_enabled != "false":
            raise RuntimeError(
                "Canary refused: QueueTriggerEnabled and OutboxDispatcherEnabled must both be false."
            )

    def reserved_object_remains(self, *, bucket: str) -> bool:
        completed = self._run(
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            CANARY_OBJECT_KEY,
            check=False,
        )
        if completed.returncode == 0:
            return True
        detail = f"{completed.stdout}\n{completed.stderr}".lower()
        # The successful HeadObject immediately after upload proves GetObject.
        # Without ListBucket, S3 intentionally returns 403 for a now-missing key.
        if any(marker in detail for marker in ("403", "404", "forbidden", "not found", "nosuchkey")):
            return False
        raise RuntimeError("Unable to check the reserved canary object in S3.")

    def upload_pdf(self, *, bucket: str, raw_pdf: bytes, path: Path) -> None:
        path.write_bytes(raw_pdf)
        completed = self._run(
            "s3api",
            "put-object",
            "--bucket",
            bucket,
            "--key",
            CANARY_OBJECT_KEY,
            "--body",
            str(path),
            "--content-type",
            "application/pdf",
            "--server-side-encryption",
            "AES256",
            "--if-none-match",
            "*",
            check=False,
        )
        if completed.returncode != 0:
            detail = f"{completed.stdout}\n{completed.stderr}".strip()
            if "PreconditionFailed" in detail or "412" in detail:
                raise RuntimeError(
                    "The reserved canary object already exists. Inspect the previous run before retrying."
                )
            raise RuntimeError((detail or "Unable to upload the reserved canary object.")[:500])

        verified = self._run(
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            CANARY_OBJECT_KEY,
            check=False,
        )
        if verified.returncode != 0:
            try:
                self.delete_pdf(bucket=bucket)
            except Exception:
                pass
            raise RuntimeError("The uploaded canary object could not be verified with HeadObject.")

    def delete_pdf(self, *, bucket: str) -> None:
        self._run(
            "s3api",
            "delete-object",
            "--bucket",
            bucket,
            "--key",
            CANARY_OBJECT_KEY,
        )

    def invoke(self, *, function_name: str, event: dict[str, object], directory: Path) -> dict[str, object]:
        event_path = directory / "event.json"
        response_path = directory / "response.json"
        event_path.write_text(json.dumps(event, separators=(",", ":")), encoding="utf-8")
        completed = self._run(
            "lambda",
            "invoke",
            "--function-name",
            function_name,
            "--cli-binary-format",
            "raw-in-base64-out",
            "--payload",
            f"fileb://{event_path}",
            str(response_path),
            timeout_seconds=930,
        )
        metadata = json.loads(completed.stdout or "{}")
        if metadata.get("FunctionError"):
            raise RuntimeError(f"Lambda returned FunctionError={metadata['FunctionError']}.")
        payload = json.loads(response_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(payload, dict):
            raise RuntimeError("Lambda canary response must be a JSON object.")
        return payload

    def _run_json(self, *arguments: str) -> dict[str, object]:
        completed = self._run(*arguments, "--output", "json")
        payload = json.loads(completed.stdout or "{}")
        if not isinstance(payload, dict):
            raise RuntimeError("AWS CLI response must be a JSON object.")
        return payload

    def _run(
        self,
        *arguments: str,
        check: bool = True,
        timeout_seconds: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            self.aws_cli,
            "--profile",
            self.profile,
            "--region",
            self.region,
            *arguments,
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "AWS CLI command failed.").strip()
            raise RuntimeError(detail[:500])
        return completed


def execute_canary(*, settings: CanarySettings, raw_pdf: bytes, run_id: str) -> dict[str, object]:
    client = AwsCliCanaryClient(profile=settings.profile, region=settings.region)
    operator_arn = client.assert_expected_identity()
    client.assert_worker_dark_mode(settings.worker_stack)
    foundation_outputs = client.stack_outputs(settings.foundation_stack)
    bucket = foundation_outputs.get("ConversionBucketName", "").strip()
    if not bucket:
        raise RuntimeError("ConversionBucketName was not found in the foundation stack outputs.")
    repository = PostgresConversionBatchRepository(
        database_url=settings.database_url,
        database_schema=settings.database_schema,
    )
    batch, job = build_canary_records(raw_pdf=raw_pdf, run_id=run_id)
    trace_id = f"trace-worker-canary-{_normalize_run_id(run_id)}"
    event = build_sqs_event(job_id=job.job_id, batch_id=batch.batch_id, trace_id=trace_id)

    with tempfile.TemporaryDirectory(prefix="gettdone-worker-canary-") as temporary_dir:
        directory = Path(temporary_dir)
        client.upload_pdf(bucket=bucket, raw_pdf=raw_pdf, path=directory / "document.pdf")
        try:
            submission = repository.create(batch=batch, jobs=[job])
            if not submission.created:
                raise RuntimeError("Canary batch idempotency key already exists.")
            repository.mark_uploaded(job.job_id)
            repository.mark_queued(job.job_id)
        except Exception:
            client.delete_pdf(bucket=bucket)
            raise

        response = client.invoke(
            function_name=settings.function_name,
            event=event,
            directory=directory,
        )

    failures = response.get("batchItemFailures")
    record = repository.get(job.job_id)
    if record is None:
        raise RuntimeError("Canary job disappeared from the PostgreSQL repository.")
    summary = summarize_record(record)
    summary.update(
        {
            "batch_id": batch.batch_id,
            "job_id": job.job_id,
            "operator_arn": operator_arn,
            "database_schema": settings.database_schema,
            "queue_trigger_enabled": False,
            "outbox_dispatcher_enabled": False,
        }
    )
    if failures:
        raise RuntimeError(f"Worker reported a batch item failure: {json.dumps(summary, sort_keys=True)}")
    if record.status != ConversionJobStatus.COMPLETED:
        raise RuntimeError(f"Canary did not complete: {json.dumps(summary, sort_keys=True)}")
    if client.reserved_object_remains(bucket=bucket):
        raise RuntimeError("Worker completed but did not delete the temporary canary source object.")
    return summary


def _normalize_run_id(run_id: str) -> str:
    normalized = (run_id or "").strip().lower()
    if _RUN_ID_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Canary run id must contain 1-32 lowercase letters or digits.")
    return normalized


def _load_settings(args) -> CanarySettings:
    env_path = Path(args.env_file).resolve()
    if not env_path.is_file():
        raise RuntimeError(f"Environment file not found: {env_path}")
    values = load_env_file(env_path)
    database_url = os.getenv("DATABASE_URL", "").strip() or values.get("DATABASE_URL", "").strip()
    database_schema = os.getenv("DATABASE_SCHEMA", "").strip() or values.get("DATABASE_SCHEMA", "").strip()
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection string.")
    if "sslmode=require" not in database_url.lower():
        raise RuntimeError("DATABASE_URL must require TLS with sslmode=require.")
    if _SCHEMA_PATTERN.fullmatch(database_schema) is None:
        raise RuntimeError("DATABASE_SCHEMA must be explicitly set to a valid schema name.")
    return CanarySettings(
        database_url=database_url,
        database_schema=database_schema,
        profile=args.profile,
        region=args.region,
        foundation_stack=args.foundation_stack,
        worker_stack=args.worker_stack,
        function_name=args.function_name,
    )


def _generate_scanned_pdf() -> bytes:
    scenario_path = _BACKEND_DIR / "tests" / "fixtures" / "pdf_scenarios" / f"{CANARY_SCENARIO}.json"
    scenario = load_scenario(scenario_path)
    raw_pdf = generate_pdf(scenario, variant="scanned")
    if not raw_pdf.startswith(b"%PDF"):
        raise RuntimeError("Synthetic corpus did not generate a valid PDF document.")
    return raw_pdf


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one dark-mode, synthetic scanned-PDF canary against the production conversion worker."
    )
    parser.add_argument("--env-file", default=str(_BACKEND_DIR / ".env"))
    parser.add_argument("--profile", default="gettdone-iac")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--foundation-stack", default="gettdone-production-foundation")
    parser.add_argument("--worker-stack", default="gettdone-production-worker")
    parser.add_argument("--function-name", default="gettdone-production-conversion-worker")
    parser.add_argument("--run-id", help="Optional lowercase alphanumeric id used for deterministic troubleshooting.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + uuid4().hex[:8]
    try:
        settings = _load_settings(args)
        summary = execute_canary(
            settings=settings,
            raw_pdf=_generate_scanned_pdf(),
            run_id=run_id,
        )
    except Exception as exc:
        print(f"CANARY_ERROR type={type(exc).__name__} detail={str(exc)[:1000]}")
        return 1
    print("CANARY_OK " + json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
