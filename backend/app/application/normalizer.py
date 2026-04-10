from datetime import datetime

from app.application.errors import InvalidFileContentError
from app.application.models import NormalizedTransaction

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d")


def normalize_transactions(transactions: list[NormalizedTransaction]) -> list[NormalizedTransaction]:
    return [normalize_transaction(item) for item in transactions]


def normalize_transaction(transaction: NormalizedTransaction) -> NormalizedTransaction:
    normalized_amount = _normalize_amount(transaction.amount, transaction.type)
    return NormalizedTransaction(
        date=_normalize_date(transaction.date),
        description=_normalize_description(transaction.description),
        amount=normalized_amount,
        type=_infer_type(normalized_amount),
    )


def _normalize_date(raw: str) -> str:
    value = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    if len(value) >= 10:
        try:
            return datetime.fromisoformat(value[:10]).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise InvalidFileContentError(f"Invalid date value after normalization: {raw!r}.")


def _normalize_description(raw: str) -> str:
    cleaned = " ".join(str(raw).strip().split())
    return cleaned.upper()


def _normalize_amount(amount: float, raw_type: str) -> float:
    hint = _type_hint(raw_type)
    value = float(amount)
    if hint == "inflow":
        return abs(value)
    if hint == "outflow":
        return -abs(value)
    return value


def _type_hint(raw_type: str) -> str | None:
    value = str(raw_type).strip().lower()
    if value in {"inflow", "credit", "entrada", "credito"}:
        return "inflow"
    if value in {"outflow", "debit", "saida", "debito"}:
        return "outflow"
    return None


def _infer_type(amount: float) -> str:
    return "inflow" if amount >= 0 else "outflow"

