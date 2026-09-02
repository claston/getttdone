import json

import pytest

from app.application.conversion.sqs_conversion_queue import SqsConversionQueuePublisher


class FakeSqsClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "sqs-message-123"}


def test_sqs_message_contains_only_opaque_routing_data() -> None:
    client = FakeSqsClient()
    publisher = SqsConversionQueuePublisher(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/conversions",
        sqs_client=client,
    )

    message_id = publisher.publish(
        job_id="job_abc123",
        batch_id="batch_abc123",
        trace_id="trace-123",
    )

    assert message_id == "sqs-message-123"
    call = client.calls[0]
    body = json.loads(call["MessageBody"])
    assert body == {
        "schema_version": 1,
        "event_type": "conversion.requested",
        "job_id": "job_abc123",
        "batch_id": "batch_abc123",
        "trace_id": "trace-123",
    }
    serialized = json.dumps(call)
    assert "filename" not in serialized
    assert "identity" not in serialized
    assert "sha256" not in serialized


@pytest.mark.parametrize("job_id", ["", "../job", "job with spaces"])
def test_sqs_publisher_rejects_invalid_job_id(job_id: str) -> None:
    publisher = SqsConversionQueuePublisher(queue_url="https://sqs.example.test/queue", sqs_client=FakeSqsClient())

    with pytest.raises(ValueError, match="job id"):
        publisher.publish(job_id=job_id, batch_id="batch_abc123", trace_id="trace-123")
