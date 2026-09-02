import pytest

from app.application.conversion.conversion_runtime_config import (
    ConversionArchitectureMode,
    ConversionExecutionMode,
    ConversionRuntimeConfig,
    ConversionUploadMode,
)


def test_conversion_runtime_config_defaults_to_legacy_fallback() -> None:
    config = ConversionRuntimeConfig.from_mapping({})

    assert config.architecture_mode == ConversionArchitectureMode.LEGACY
    assert config.upload_mode == ConversionUploadMode.PROXY
    assert config.execution_mode == ConversionExecutionMode.INLINE_LEGACY
    assert config.batch_max_files == 12


def test_conversion_runtime_config_defaults_async_aws_to_direct_upload_and_sqs() -> None:
    config = ConversionRuntimeConfig.from_mapping(
        {"CONVERSION_ARCHITECTURE_MODE": "async_aws"},
    )

    assert config.architecture_mode == ConversionArchitectureMode.ASYNC_AWS
    assert config.upload_mode == ConversionUploadMode.DIRECT_S3
    assert config.execution_mode == ConversionExecutionMode.SQS_LAMBDA


def test_conversion_runtime_config_accepts_shared_inline_operational_fallback() -> None:
    config = ConversionRuntimeConfig.from_mapping(
        {
            "CONVERSION_ARCHITECTURE_MODE": "async_aws",
            "CONVERSION_UPLOAD_MODE": "proxy",
            "CONVERSION_EXECUTION_MODE": "inline_shared",
        },
    )

    assert config.upload_mode == ConversionUploadMode.PROXY
    assert config.execution_mode == ConversionExecutionMode.INLINE_SHARED


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        (
            {
                "CONVERSION_ARCHITECTURE_MODE": "legacy",
                "CONVERSION_UPLOAD_MODE": "direct_s3",
            },
            "legacy architecture requires proxy upload",
        ),
        (
            {
                "CONVERSION_ARCHITECTURE_MODE": "legacy",
                "CONVERSION_EXECUTION_MODE": "sqs_lambda",
            },
            "legacy architecture requires inline_legacy execution",
        ),
        (
            {
                "CONVERSION_ARCHITECTURE_MODE": "async_aws",
                "CONVERSION_EXECUTION_MODE": "inline_legacy",
            },
            "async_aws architecture requires shared execution",
        ),
        (
            {
                "CONVERSION_ARCHITECTURE_MODE": "async_aws",
                "CONVERSION_UPLOAD_MODE": "proxy",
                "CONVERSION_EXECUTION_MODE": "sqs_lambda",
            },
            "proxy upload requires inline_shared execution",
        ),
        (
            {
                "CONVERSION_ARCHITECTURE_MODE": "async_aws",
                "CONVERSION_UPLOAD_MODE": "direct_s3",
                "CONVERSION_EXECUTION_MODE": "inline_shared",
            },
            "direct_s3 upload requires sqs_lambda execution",
        ),
    ],
)
def test_conversion_runtime_config_rejects_unsafe_hybrid_modes(environment: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ConversionRuntimeConfig.from_mapping(environment)


@pytest.mark.parametrize("value", ["0", "13", "not-a-number"])
def test_conversion_runtime_config_rejects_invalid_batch_limit(value: str) -> None:
    with pytest.raises(ValueError, match="CONVERSION_BATCH_MAX_FILES"):
        ConversionRuntimeConfig.from_mapping({"CONVERSION_BATCH_MAX_FILES": value})


def test_conversion_runtime_config_accepts_smaller_batch_limit_for_emergency_control() -> None:
    config = ConversionRuntimeConfig.from_mapping({"CONVERSION_BATCH_MAX_FILES": "5"})

    assert config.batch_max_files == 5
