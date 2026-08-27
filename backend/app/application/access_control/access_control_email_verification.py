from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from app.application.errors import (
    EmailVerificationRateLimitedError,
    InvalidEmailVerificationTokenError,
    InvalidUserTokenError,
)

if TYPE_CHECKING:
    from app.application.access_control import AccessControlService, EmailVerificationToken, RegisteredUser


class AccessControlEmailVerificationComponent:
    def __init__(self, service: AccessControlService) -> None:
        self._service = service

    @staticmethod
    def row_is_verified(row) -> bool:
        if row is None:
            return False
        keys = row.keys() if hasattr(row, "keys") else ()
        if "email_verification_status" not in keys:
            return True
        return str(row["email_verification_status"] or "verified").strip().lower() == "verified"

    def issue_token(self, *, user_id: str, enforce_resend_limits: bool = False) -> EmailVerificationToken:
        service = self._service
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise InvalidUserTokenError
        now = service.now_provider()
        now_iso = now.isoformat()

        with service._lock:
            with service._connect() as conn:
                user = service._fetchone(
                    conn,
                    """
                    SELECT id, name, email, is_active, email_verification_status
                    FROM users
                    WHERE id = ?
                    """,
                    (normalized_user_id,),
                )
                if user is None or not service._row_is_active(user) or self.row_is_verified(user):
                    raise InvalidUserTokenError

                if enforce_resend_limits:
                    self._enforce_resend_limits(conn=conn, user_id=normalized_user_id, now=now)

                service._execute(
                    conn,
                    """
                    UPDATE email_verification_tokens
                    SET invalidated_at = ?
                    WHERE user_id = ?
                      AND consumed_at IS NULL
                      AND invalidated_at IS NULL
                    """,
                    (now_iso, normalized_user_id),
                )
                raw_token = secrets.token_urlsafe(32)
                token_hash = self._hash_token(raw_token)
                token_id = f"evt_{uuid4().hex[:24]}"
                expires_at = now + timedelta(seconds=service.email_verification_ttl_seconds)
                service._execute(
                    conn,
                    """
                    INSERT INTO email_verification_tokens (
                        id,
                        user_id,
                        token_hash,
                        created_at,
                        expires_at,
                        consumed_at,
                        invalidated_at,
                        delivery_status,
                        sent_at,
                        provider_message_id
                    )
                    VALUES (?, ?, ?, ?, ?, NULL, NULL, 'pending', NULL, NULL)
                    """,
                    (
                        token_id,
                        normalized_user_id,
                        token_hash,
                        now_iso,
                        expires_at.isoformat(),
                    ),
                )
                conn.commit()

        return service._email_verification_token_factory(
            token_id=token_id,
            user_id=normalized_user_id,
            email=str(user["email"]),
            name=str(user["name"] or ""),
            token=raw_token,
            expires_at=expires_at.isoformat(),
        )

    def issue_token_for_email(self, *, email: str) -> EmailVerificationToken | None:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return None
        with self._service._lock:
            with self._service._connect() as conn:
                row = self._service._fetchone(
                    conn,
                    """
                    SELECT id, is_active, email_verification_status
                    FROM users
                    WHERE lower(email) = ?
                    """,
                    (normalized_email,),
                )
        if row is None or not self._service._row_is_active(row) or self.row_is_verified(row):
            return None
        return self.issue_token(user_id=str(row["id"]), enforce_resend_limits=True)

    def mark_delivery(self, *, token_id: str, status: str, provider_message_id: str | None = None) -> None:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"sent", "failed"}:
            raise ValueError("Unsupported email verification delivery status")
        now_iso = self._service.now_provider().isoformat()
        with self._service._lock:
            with self._service._connect() as conn:
                self._service._execute(
                    conn,
                    """
                    UPDATE email_verification_tokens
                    SET delivery_status = ?, sent_at = ?, provider_message_id = ?
                    WHERE id = ?
                    """,
                    (
                        normalized_status,
                        now_iso if normalized_status == "sent" else None,
                        str(provider_message_id or "").strip() or None,
                        str(token_id or "").strip(),
                    ),
                )
                conn.commit()

    def confirm_token(self, *, token: str) -> RegisteredUser:
        raw_token = str(token or "").strip()
        if not raw_token:
            raise InvalidEmailVerificationTokenError
        token_hash = self._hash_token(raw_token)
        now = self._service.now_provider()
        now_iso = now.isoformat()

        with self._service._lock:
            with self._service._connect() as conn:
                row = self._service._fetchone(
                    conn,
                    """
                    SELECT
                        email_verification_tokens.id AS token_id,
                        email_verification_tokens.expires_at,
                        email_verification_tokens.consumed_at,
                        email_verification_tokens.invalidated_at,
                        users.id,
                        users.name,
                        users.email,
                        users.is_admin,
                        users.is_active
                    FROM email_verification_tokens
                    JOIN users ON users.id = email_verification_tokens.user_id
                    WHERE email_verification_tokens.token_hash = ?
                    """,
                    (token_hash,),
                )
                if row is None or row["consumed_at"] or row["invalidated_at"]:
                    raise InvalidEmailVerificationTokenError
                expires_at = self._service._parse_usage_datetime(str(row["expires_at"]), fallback=now)
                if expires_at <= now:
                    raise InvalidEmailVerificationTokenError

                cursor = self._service._execute(
                    conn,
                    """
                    UPDATE email_verification_tokens
                    SET consumed_at = ?
                    WHERE id = ? AND consumed_at IS NULL AND invalidated_at IS NULL
                    """,
                    (now_iso, str(row["token_id"])),
                )
                if getattr(cursor, "rowcount", 1) != 1:
                    conn.rollback()
                    raise InvalidEmailVerificationTokenError
                self._service._execute(
                    conn,
                    """
                    UPDATE users
                    SET email_verification_status = 'verified', email_verified_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, str(row["id"])),
                )
                self._service._execute(
                    conn,
                    """
                    UPDATE email_verification_tokens
                    SET invalidated_at = ?
                    WHERE user_id = ? AND id <> ? AND consumed_at IS NULL AND invalidated_at IS NULL
                    """,
                    (now_iso, str(row["id"]), str(row["token_id"])),
                )
                conn.commit()

        return self._service._registered_user_factory(
            user_id=str(row["id"]),
            email=str(row["email"]),
            name=str(row["name"] or ""),
            token=self._service._encode_token(str(row["id"])),
            is_admin=self._service._row_is_admin(row),
            is_active=self._service._row_is_active(row),
            email_verification_status="verified",
            email_verified_at=now_iso,
        )

    def _enforce_resend_limits(self, *, conn, user_id: str, now) -> None:
        service = self._service
        latest = service._fetchone(
            conn,
            """
            SELECT sent_at
            FROM email_verification_tokens
            WHERE user_id = ? AND delivery_status = 'sent' AND sent_at IS NOT NULL
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        if latest is not None:
            sent_at = service._parse_usage_datetime(str(latest["sent_at"]), fallback=now)
            if (now - sent_at).total_seconds() < service.email_verification_resend_cooldown_seconds:
                raise EmailVerificationRateLimitedError

        since = (now - timedelta(days=1)).isoformat()
        count_row = service._fetchone(
            conn,
            """
            SELECT COUNT(1) AS total
            FROM email_verification_tokens
            WHERE user_id = ? AND delivery_status = 'sent' AND sent_at >= ?
            """,
            (user_id, since),
        )
        if count_row is not None and int(count_row["total"] or 0) >= service.email_verification_daily_limit:
            raise EmailVerificationRateLimitedError

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
