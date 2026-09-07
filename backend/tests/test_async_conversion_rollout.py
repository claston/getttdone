from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.application.access_control import IdentityContext, RegisteredUser
from app.application.conversion.async_conversion_rollout import AsyncConversionRolloutPolicy


@dataclass
class FakeAccessControl:
    user: RegisteredUser

    def get_user_by_id(self, user_id: str) -> RegisteredUser:
        assert user_id == self.user.user_id
        return self.user


def _user(email: str = "a@a.com.br") -> RegisteredUser:
    return RegisteredUser(
        user_id="usr_canary",
        email=email,
        name="Canary",
        token="user-token",
    )


def test_rollout_policy_normalizes_email_allowlist_and_allows_only_registered_user() -> None:
    policy = AsyncConversionRolloutPolicy.from_mapping(
        {"CONVERSION_ASYNC_USER_EMAIL_ALLOWLIST": " A@A.COM.BR, second@example.com "}
    )
    access_control = FakeAccessControl(user=_user())

    assert policy.enabled is True
    assert policy.allows(
        identity=IdentityContext(identity_type="user", identity_id="usr_canary", quota_limit=10),
        access_control_service=access_control,
    )
    assert not policy.allows(
        identity=IdentityContext(identity_type="anonymous", identity_id="anon_123", quota_limit=3),
        access_control_service=access_control,
    )


def test_rollout_policy_rejects_non_allowlisted_user() -> None:
    policy = AsyncConversionRolloutPolicy.from_mapping(
        {"CONVERSION_ASYNC_USER_EMAIL_ALLOWLIST": "a@a.com.br"}
    )

    assert not policy.allows(
        identity=IdentityContext(identity_type="user", identity_id="usr_canary", quota_limit=10),
        access_control_service=FakeAccessControl(user=_user("other@example.com")),
    )


def test_rollout_policy_rejects_invalid_configured_email() -> None:
    with pytest.raises(ValueError, match="valid email"):
        AsyncConversionRolloutPolicy.from_mapping(
            {"CONVERSION_ASYNC_USER_EMAIL_ALLOWLIST": "not-an-email"}
        )
