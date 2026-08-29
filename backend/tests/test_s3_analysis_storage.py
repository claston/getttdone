from io import BytesIO
from pathlib import Path

from app.application.models import AnalysisData, TransactionRow
from app.application.s3_analysis_storage import S3AnalysisStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = bytes(kwargs["Body"])

    def get_object(self, **kwargs):
        return {"Body": BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

    def list_objects_v2(self, **kwargs):
        prefix = kwargs["Prefix"]
        return {
            "Contents": [
                {"Key": key}
                for bucket, key in sorted(self.objects)
                if bucket == kwargs["Bucket"] and key.startswith(prefix)
            ],
            "IsTruncated": False,
        }


def _analysis() -> AnalysisData:
    rows = [
        TransactionRow(
            date="2026-08-01",
            description="PIX recebido",
            amount=100.0,
            category="Outros",
            reconciliation_status="unmatched",
        )
    ]
    return AnalysisData(
        analysis_id="an_shared123",
        file_type="pdf",
        upload_filename="extrato.pdf",
        transactions_total=1,
        total_inflows=100.0,
        total_outflows=0.0,
        net_total=100.0,
        preview_transactions=rows,
        report_transactions=rows,
    )


def test_s3_analysis_storage_shares_lambda_results_with_api_process(tmp_path: Path) -> None:
    client = FakeS3Client()
    worker_storage = S3AnalysisStorage(
        root_dir=tmp_path / "lambda",
        bucket="private-conversions",
        prefix="results",
        s3_client=client,
    )
    worker_storage.save_analysis(_analysis())
    worker_storage.set_convert_owner("an_shared123", "user", "usr_123")

    api_storage = S3AnalysisStorage(
        root_dir=tmp_path / "render",
        bucket="private-conversions",
        prefix="results",
        s3_client=client,
    )

    report_path = api_storage.get_convert_report_path("an_shared123", "ofx")
    api_storage.assert_convert_owner("an_shared123", "user", "usr_123")

    assert report_path.exists()
    assert report_path.read_text(encoding="utf-8").startswith("OFXHEADER:100")
    assert any(key.endswith("/analysis.json") for _bucket, key in client.objects)
    assert any(key.endswith("/converted.ofx") for _bucket, key in client.objects)
