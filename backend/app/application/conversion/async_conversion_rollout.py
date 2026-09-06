from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from app.application.errors import InvalidSessionTokenError, InvalidUserTokenError

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class AsyncConversionRolloutPolicy:
    allowed_user_emails: frozenset[str]

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> AsyncConversionRolloutPolicy:
        raw = values.get("CONVERSION_ASYNC_USER_EMAIL_ALLOWLIST", "")
        emails = frozenset(item.strip().lower() for item in raw.split(",") if item.strip())
        if any(_EMAIL_PATTERN.fullmatch(email) is None for email in emails):
            raise ValueError("CONVERSION_ASYNC_USER_EMAIL_ALLOWLIST must contain valid email addresses.")
        return cls(allowed_user_emails=emails)

    @property
    def enabled(self) -> bool:
        return bool(self.allowed_user_emails)

    def allows(self, *, identity, access_control_service) -> bool:
        if not self.enabled or identity is None or identity.identity_type != "user":
            return False
        try:
            user = access_control_service.get_user_by_id(identity.identity_id)
        except (InvalidSessionTokenError, InvalidUserTokenError):
            return False
        return user.email.strip().lower() in self.allowed_user_emails
