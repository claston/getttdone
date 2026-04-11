from pathlib import Path

from app.application.csv_parser import parse_csv_transactions
from app.application.errors import InvalidFileContentError, UnsupportedFileTypeError
from app.application.models import NormalizedTransaction
from app.application.xlsx_parser import parse_xlsx_transactions

_SHEET_ALLOWED_EXTENSIONS = {"csv", "xlsx"}


def parse_operational_sheet_rows(filename: str, raw_bytes: bytes) -> list[NormalizedTransaction]:
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in _SHEET_ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError

    if extension == "csv":
        return parse_csv_transactions(raw_bytes)

    if extension == "xlsx":
        return parse_xlsx_transactions(raw_bytes)

    raise InvalidFileContentError("Unsupported operational sheet content.")
