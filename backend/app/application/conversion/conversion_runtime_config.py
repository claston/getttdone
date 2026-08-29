from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class ConversionArchitectureMode(str, Enum):
    LEGACY = "legacy"
    ASYNC_AWS = "async_aws"


class ConversionUploadMode(str, Enum):
    PROXY = "proxy"
    DIRECT_S3 = "direct_s3"


class ConversionExecutionMode(str, Enum):
    INLINE_LEGACY = "inline_legacy"
    INLINE_SHARED = "inline_shared"
    SQS_LAMBDA = "sqs_lambda"


@dataclass(frozen=True, slots=True)
class ConversionRuntimeConfig:
    architecture_mode: ConversionArchitectureMode
    upload_mode: ConversionUploadMode
    execution_mode: ConversionExecutionMode
    batch_max_files: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> ConversionRuntimeConfig:
        architecture_mode = cls._parse_enum(
            ConversionArchitectureMode,
            values.get("CONVERSION_ARCHITECTURE_MODE", ConversionArchitectureMode.LEGACY.value),
            "CONVERSION_ARCHITECTURE_MODE",
        )

        if architecture_mode == ConversionArchitectureMode.LEGACY:
            default_upload = ConversionUploadMode.PROXY
            default_execution = ConversionExecutionMode.INLINE_LEGACY
        else:
            default_upload = ConversionUploadMode.DIRECT_S3
            default_execution = ConversionExecutionMode.SQS_LAMBDA

        upload_mode = cls._parse_enum(
            ConversionUploadMode,
            values.get("CONVERSION_UPLOAD_MODE", default_upload.value),
            "CONVERSION_UPLOAD_MODE",
        )
        execution_mode = cls._parse_enum(
            ConversionExecutionMode,
            values.get("CONVERSION_EXECUTION_MODE", default_execution.value),
            "CONVERSION_EXECUTION_MODE",
        )
        batch_max_files = cls._parse_batch_max_files(values.get("CONVERSION_BATCH_MAX_FILES", "12"))

        if architecture_mode == ConversionArchitectureMode.LEGACY:
            if upload_mode != ConversionUploadMode.PROXY:
                raise ValueError("legacy architecture requires proxy upload")
            if execution_mode != ConversionExecutionMode.INLINE_LEGACY:
                raise ValueError("legacy architecture requires inline_legacy execution")
        elif execution_mode == ConversionExecutionMode.INLINE_LEGACY:
            raise ValueError("async_aws architecture requires shared execution")
        elif upload_mode == ConversionUploadMode.PROXY and execution_mode != ConversionExecutionMode.INLINE_SHARED:
            raise ValueError("proxy upload requires inline_shared execution")
        elif upload_mode == ConversionUploadMode.DIRECT_S3 and execution_mode != ConversionExecutionMode.SQS_LAMBDA:
            raise ValueError("direct_s3 upload requires sqs_lambda execution")

        return cls(
            architecture_mode=architecture_mode,
            upload_mode=upload_mode,
            execution_mode=execution_mode,
            batch_max_files=batch_max_files,
        )

    @staticmethod
    def _parse_enum(enum_type, value: str, variable_name: str):
        try:
            return enum_type((value or "").strip().lower())
        except ValueError as exc:
            supported = ", ".join(item.value for item in enum_type)
            raise ValueError(f"Invalid {variable_name}; expected one of: {supported}.") from exc

    @staticmethod
    def _parse_batch_max_files(value: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("CONVERSION_BATCH_MAX_FILES must be an integer between 1 and 12.") from exc
        if not 1 <= parsed <= 12:
            raise ValueError("CONVERSION_BATCH_MAX_FILES must be between 1 and 12.")
        return parsed
