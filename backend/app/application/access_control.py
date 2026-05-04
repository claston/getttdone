import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Callable
from uuid import uuid4

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency for postgres deployments
    psycopg = None
    dict_row = None

from app.application.errors import (
    FileTooLargeError,
    InvalidCredentialsError,
    InvalidUserTokenError,
    QuotaExceededError,
    UserAlreadyExistsError,
)

ANONYMOUS_QUOTA_LIMIT = 3
REGISTERED_QUOTA_LIMIT = 10
MAX_UPLOAD_SIZE_BYTES = 2 * 1024 * 1024
PAID_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
PAID_MAX_PAGES_PER_FILE = 100
PASSWORD_HASH_ITERATIONS = 390_000
QUOTA_WINDOW_DAYS = 7
MONTHLY_QUOTA_WINDOW_DAYS = 30
DEFAULT_PUBLIC_PLANS = [
    ("essencial", "Essencial", 1, "BRL", 2990, 150),
    ("profissional", "Profissional", 1, "BRL", 3990, 300),
    ("escritorio", "Escritorio", 1, "BRL", 4990, 500),
]


@dataclass(frozen=True)
class IdentityContext:
    identity_type: str
    identity_id: str
    quota_limit: int
    quota_mode: str = "conversion"
    quota_window_days: int = QUOTA_WINDOW_DAYS
    max_upload_size_bytes: int = MAX_UPLOAD_SIZE_BYTES
    max_pages_per_file: int = 5
    plan_code: str | None = None
    plan_name: str | None = None


@dataclass(frozen=True)
class RegisteredUser:
    user_id: str
    email: str
    name: str
    token: str


class AccessControlService:
    def __init__(
        self,
        state_file: Path,
        token_secret: str,
        database_url: str | None = None,
        database_schema: str | None = None,
        anonymous_quota_limit: int = ANONYMOUS_QUOTA_LIMIT,
        registered_quota_limit: int = REGISTERED_QUOTA_LIMIT,
        quota_window_days: int = QUOTA_WINDOW_DAYS,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.state_file = state_file
        self.db_file = state_file.with_suffix(".db")
        self.database_url = (database_url or "").strip()
        self.database_schema = self._normalize_database_schema(database_schema)
        self._use_postgres = self.database_url.startswith("postgres://") or self.database_url.startswith(
            "postgresql://"
        )
        self.token_secret = token_secret.encode("utf-8")
        self.anonymous_quota_limit = anonymous_quota_limit
        self.registered_quota_limit = registered_quota_limit
        self.quota_window_days = max(1, int(quota_window_days))
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        if not self._use_postgres:
            self.db_file.parent.mkdir(parents=True, exist_ok=True)
        elif psycopg is None:
            raise RuntimeError("PostgreSQL support requires psycopg. Install backend requirements.")
        self._init_db()

    def resolve_identity(
        self,
        anonymous_fingerprint: str | None,
        user_token: str | None,
    ) -> IdentityContext:
        if user_token:
            user_id = self._decode_token(user_token)
            if not self._user_exists(user_id):
                raise InvalidUserTokenError
            active_plan = self._read_active_user_plan(user_id=user_id)
            if active_plan is not None:
                return IdentityContext(
                    identity_type="user",
                    identity_id=user_id,
                    quota_limit=int(active_plan["quota_limit"]),
                    quota_mode=str(active_plan["quota_mode"]),
                    quota_window_days=int(active_plan["quota_window_days"]),
                    max_upload_size_bytes=int(active_plan["max_upload_size_bytes"]),
                    max_pages_per_file=int(active_plan["max_pages_per_file"]),
                    plan_code=str(active_plan["code"]),
                    plan_name=str(active_plan["name"]),
                )
            return IdentityContext(
                identity_type="user",
                identity_id=user_id,
                quota_limit=self.registered_quota_limit,
                quota_mode="conversion",
                quota_window_days=self.quota_window_days,
            )

        fingerprint = (anonymous_fingerprint or "").strip()
        if not fingerprint:
            raise InvalidUserTokenError
        anon_id = self._ensure_anonymous_identity(fingerprint)
        return IdentityContext(
            identity_type="anonymous",
            identity_id=anon_id,
            quota_limit=self.anonymous_quota_limit,
            quota_mode="conversion",
            quota_window_days=self.quota_window_days,
        )

    def register_user(self, name: str, email: str, password: str) -> RegisteredUser:
        normalized_email = email.strip().lower()
        now = self.now_provider().isoformat()
        user_id = f"usr_{uuid4().hex[:12]}"
        salt = secrets.token_hex(8)
        password_hash = self._hash_password(password=password, salt=salt)
        with self._lock:
            with self._connect() as conn:
                existing = self._fetchone(conn, "SELECT id FROM users WHERE email = ?", (normalized_email,))
                if existing is not None:
                    raise UserAlreadyExistsError
                self._execute(
                    conn,
                    """
                    INSERT INTO users (
                        id,
                        name,
                        email,
                        password_hash,
                        password_salt,
                        auth_provider,
                        provider_user_id,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        name.strip(),
                        normalized_email,
                        password_hash,
                        salt,
                        "local",
                        None,
                        now,
                        now,
                    ),
                )
                conn.commit()
        return RegisteredUser(
            user_id=user_id,
            email=normalized_email,
            name=name.strip(),
            token=self._encode_token(user_id),
        )

    def authenticate_user(self, email: str, password: str) -> RegisteredUser:
        normalized_email = email.strip().lower()
        with self._lock:
            with self._connect() as conn:
                user = self._fetchone(
                    conn,
                    "SELECT id, name, email, password_hash, password_salt FROM users WHERE email = ?",
                    (normalized_email,),
                )
                if user is None:
                    raise InvalidCredentialsError
                if not self._verify_password(
                    password=password,
                    stored_hash=str(user["password_hash"] or ""),
                    stored_salt=str(user["password_salt"] or ""),
                ):
                    raise InvalidCredentialsError
                return RegisteredUser(
                    user_id=str(user["id"]),
                    email=str(user["email"]),
                    name=str(user["name"] or ""),
                    token=self._encode_token(str(user["id"])),
                )

    def get_user_by_token(self, user_token: str) -> RegisteredUser:
        user_id = self._decode_token(user_token)
        with self._lock:
            with self._connect() as conn:
                user = self._fetchone(
                    conn,
                    "SELECT id, name, email FROM users WHERE id = ?",
                    (user_id,),
                )
                if user is None:
                    raise InvalidUserTokenError
                return RegisteredUser(
                    user_id=str(user["id"]),
                    email=str(user["email"]),
                    name=str(user["name"] or ""),
                    token=user_token,
                )

    def register_or_authenticate_google_user(
        self,
        *,
        provider_user_id: str,
        email: str,
        name: str,
    ) -> RegisteredUser:
        normalized_email = email.strip().lower()
        provider_user_id = provider_user_id.strip()
        display_name = name.strip() or normalized_email.split("@", 1)[0]
        now = self.now_provider().isoformat()

        with self._lock:
            with self._connect() as conn:
                row = self._fetchone(
                    conn,
                    """
                    SELECT id, name, email
                    FROM users
                    WHERE auth_provider = 'google' AND provider_user_id = ?
                    """,
                    (provider_user_id,),
                )
                if row is not None:
                    user_id = str(row["id"])
                    self._execute(
                        conn,
                        """
                        UPDATE users
                        SET name = ?, email = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (display_name, normalized_email, now, user_id),
                    )
                    conn.commit()
                    return RegisteredUser(
                        user_id=user_id,
                        email=normalized_email,
                        name=display_name,
                        token=self._encode_token(user_id),
                    )

                existing_by_email = self._fetchone(
                    conn,
                    "SELECT id, name, email FROM users WHERE email = ?",
                    (normalized_email,),
                )
                if existing_by_email is not None:
                    user_id = str(existing_by_email["id"])
                    self._execute(
                        conn,
                        """
                        UPDATE users
                        SET name = ?, auth_provider = 'google', provider_user_id = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (display_name, provider_user_id, now, user_id),
                    )
                    conn.commit()
                    return RegisteredUser(
                        user_id=user_id,
                        email=normalized_email,
                        name=display_name,
                        token=self._encode_token(user_id),
                    )

                user_id = f"usr_{uuid4().hex[:12]}"
                self._execute(
                    conn,
                    """
                    INSERT INTO users (
                        id,
                        name,
                        email,
                        password_hash,
                        password_salt,
                        auth_provider,
                        provider_user_id,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        display_name,
                        normalized_email,
                        "",
                        "",
                        "google",
                        provider_user_id,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return RegisteredUser(
                    user_id=user_id,
                    email=normalized_email,
                    name=display_name,
                    token=self._encode_token(user_id),
                )

    def create_google_oauth_state(self, *, next_path: str, ttl_seconds: int = 600) -> tuple[str, str]:
        state = f"gst_{secrets.token_urlsafe(24)}"
        code_verifier = secrets.token_urlsafe(64)
        now = self.now_provider()
        expires_at = (now + timedelta(seconds=max(60, int(ttl_seconds)))).isoformat()
        with self._lock:
            with self._connect() as conn:
                self._execute(
                    conn,
                    """
                    INSERT INTO google_oauth_states (
                        state,
                        code_verifier,
                        next_path,
                        created_at,
                        expires_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        state,
                        code_verifier,
                        self._normalize_next_path(next_path),
                        now.isoformat(),
                        expires_at,
                    ),
                )
                conn.commit()
        return state, code_verifier

    def consume_google_oauth_state(self, *, state: str) -> dict[str, str] | None:
        normalized_state = state.strip()
        if not normalized_state:
            return None
        now = self.now_provider()
        with self._lock:
            with self._connect() as conn:
                row = self._fetchone(
                    conn,
                    """
                    SELECT state, code_verifier, next_path, expires_at
                    FROM google_oauth_states
                    WHERE state = ?
                    """,
                    (normalized_state,),
                )
                self._execute(conn, "DELETE FROM google_oauth_states WHERE state = ?", (normalized_state,))
                self._execute(conn, "DELETE FROM google_oauth_states WHERE expires_at < ?", (now.isoformat(),))
                conn.commit()

        if row is None:
            return None

        expires_at_raw = str(row["expires_at"] or "").strip()
        if not expires_at_raw:
            return None
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            return None

        return {
            "state": str(row["state"]),
            "code_verifier": str(row["code_verifier"]),
            "next_path": self._normalize_next_path(str(row["next_path"])),
        }

    def assert_upload_size(self, raw_bytes: bytes, max_upload_size_bytes: int = MAX_UPLOAD_SIZE_BYTES) -> None:
        if len(raw_bytes) > max(1, int(max_upload_size_bytes)):
            raise FileTooLargeError

    def ensure_quota_available(self, identity: IdentityContext, *, required_units: int = 1) -> None:
        usage = self._read_usage(identity)
        units = max(1, int(required_units))
        if (int(usage["used_count"]) + units) > identity.quota_limit:
            raise QuotaExceededError

    def consume_quota(self, identity: IdentityContext, *, consumed_units: int = 1) -> int:
        units = max(1, int(consumed_units))
        with self._lock:
            usage = self._read_usage(identity)
            if (int(usage["used_count"]) + units) > identity.quota_limit:
                raise QuotaExceededError
            used_count = int(usage["used_count"]) + units
            window_started_at = usage["window_started_at"].isoformat()
            with self._connect() as conn:
                self._execute(
                    conn,
                    """
                    INSERT INTO usage (
                        identity_type,
                        identity_id,
                        used_count,
                        quota_limit,
                        updated_at,
                        window_started_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(identity_type, identity_id)
                    DO UPDATE SET
                      used_count=excluded.used_count,
                      quota_limit=excluded.quota_limit,
                      updated_at=excluded.updated_at,
                      window_started_at=excluded.window_started_at
                    """,
                    (
                        identity.identity_type,
                        identity.identity_id,
                        used_count,
                        identity.quota_limit,
                        self.now_provider().isoformat(),
                        window_started_at,
                    ),
                )
                conn.commit()
            return identity.quota_limit - used_count

    def get_remaining_quota(self, identity: IdentityContext) -> int:
        usage = self._read_usage(identity)
        return max(identity.quota_limit - usage["used_count"], 0)

    def get_quota_reset_at(self, identity: IdentityContext) -> str:
        usage = self._read_usage(identity)
        reset_at = usage["window_started_at"] + timedelta(days=max(1, int(identity.quota_window_days)))
        return reset_at.isoformat()

    def record_user_conversion(
        self,
        *,
        user_id: str,
        processing_id: str,
        filename: str,
        model: str,
        conversion_type: str,
        status: str,
        transactions_count: int | None,
        pages_count: int | None = None,
        created_at: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                self._execute(
                    conn,
                    """
                    INSERT INTO user_conversions (
                      analysis_id,
                      user_id,
                      created_at,
                      expires_at,
                      filename,
                      model,
                      conversion_type,
                      status,
                      transactions_count,
                      pages_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(analysis_id)
                    DO UPDATE SET
                      user_id=excluded.user_id,
                      created_at=excluded.created_at,
                      expires_at=excluded.expires_at,
                      filename=excluded.filename,
                      model=excluded.model,
                      conversion_type=excluded.conversion_type,
                      status=excluded.status,
                      transactions_count=excluded.transactions_count,
                      pages_count=excluded.pages_count
                    """,
                    (
                        processing_id,
                        user_id,
                        created_at or self.now_provider().isoformat(),
                        expires_at,
                        filename.strip() or f"{processing_id}.pdf",
                        model.strip() or "Nao identificado",
                        conversion_type.strip() or "pdf-ofx",
                        status.strip() or "Sucesso",
                        transactions_count,
                        pages_count,
                    ),
                )
                conn.commit()

    def list_user_conversions(self, *, user_id: str, limit: int = 20) -> list[dict[str, str | int]]:
        with self._lock:
            with self._connect() as conn:
                rows = self._fetchall(
                    conn,
                    """
                    SELECT analysis_id, created_at, expires_at, filename, model, conversion_type, status, transactions_count, pages_count
                    FROM user_conversions
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, max(1, min(limit, 100))),
                )

        now = self.now_provider()
        items: list[dict[str, str | int]] = []
        for row in rows:
            status = str(row["status"] or "Sucesso")
            expires_at = str(row["expires_at"] or "").strip()
            if expires_at and self._is_expired(expires_at, now):
                status = "Expirado"
            item: dict[str, str | int] = {
                "processing_id": str(row["analysis_id"]),
                "created_at": str(row["created_at"]),
                "filename": str(row["filename"]),
                "model": str(row["model"]),
                "conversion_type": str(row["conversion_type"]),
                "status": status,
            }
            tx_count = row["transactions_count"]
            if isinstance(tx_count, int):
                item["transactions_count"] = tx_count
            pg_count = row["pages_count"]
            if isinstance(pg_count, int):
                item["pages_count"] = pg_count
            items.append(item)
        return items

    def list_public_plans(self) -> list[dict[str, str | int]]:
        with self._lock:
            with self._connect() as conn:
                rows = self._fetchall(
                    conn,
                    """
                    SELECT
                      id,
                      code,
                      name,
                      version,
                      currency,
                      price_cents,
                      billing_period,
                      quota_mode,
                      quota_limit,
                      quota_window_days,
                      max_upload_size_bytes,
                      max_pages_per_file
                    FROM plan_versions
                    WHERE is_public = ? AND is_active = ?
                    ORDER BY code ASC, version DESC
                    """,
                    (self._true_value(), self._true_value()),
                )
        items: list[dict[str, str | int]] = []
        for row in rows:
            items.append(
                {
                    "id": str(row["id"]),
                    "code": str(row["code"]),
                    "name": str(row["name"]),
                    "version": int(row["version"]),
                    "currency": str(row["currency"]),
                    "price_cents": int(row["price_cents"]),
                    "billing_period": str(row["billing_period"]),
                    "quota_mode": str(row["quota_mode"]),
                    "quota_limit": int(row["quota_limit"]),
                    "quota_window_days": int(row["quota_window_days"]),
                    "max_upload_size_bytes": int(row["max_upload_size_bytes"]),
                    "max_pages_per_file": int(row["max_pages_per_file"]),
                }
            )
        return items

    def activate_user_plan(self, *, user_id: str, plan_code: str) -> dict[str, str | int]:
        normalized_code = str(plan_code or "").strip().lower()
        if not normalized_code:
            raise ValueError("plan_code is required")
        now_iso = self.now_provider().isoformat()

        with self._lock:
            with self._connect() as conn:
                if self._fetchone(conn, "SELECT id FROM users WHERE id = ?", (user_id,)) is None:
                    raise InvalidUserTokenError
                plan = self._fetchone(
                    conn,
                    """
                    SELECT
                      id,
                      code,
                      name,
                      version,
                      quota_mode,
                      quota_limit,
                      quota_window_days,
                      max_upload_size_bytes,
                      max_pages_per_file
                    FROM plan_versions
                    WHERE code = ? AND is_active = ?
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (normalized_code, self._true_value()),
                )
                if plan is None:
                    raise ValueError("plan not found")

                self._execute(
                    conn,
                    """
                    UPDATE user_plan_subscriptions
                    SET status = 'ended', ended_at = ?
                    WHERE user_id = ? AND status = 'active'
                    """,
                    (now_iso, user_id),
                )
                self._execute(
                    conn,
                    """
                    INSERT INTO user_plan_subscriptions (
                      id,
                      user_id,
                      plan_version_id,
                      status,
                      started_at,
                      ended_at
                    )
                    VALUES (?, ?, ?, 'active', ?, NULL)
                    """,
                    (
                        f"sub_{uuid4().hex[:16]}",
                        user_id,
                        str(plan["id"]),
                        now_iso,
                    ),
                )
                # Reset usage on plan change so previous free-conversion usage does not contaminate paid pages.
                self._execute(
                    conn,
                    """
                    INSERT INTO usage (
                      identity_type,
                      identity_id,
                      used_count,
                      quota_limit,
                      updated_at,
                      window_started_at
                    )
                    VALUES (?, ?, 0, ?, ?, ?)
                    ON CONFLICT(identity_type, identity_id)
                    DO UPDATE SET
                      used_count=excluded.used_count,
                      quota_limit=excluded.quota_limit,
                      updated_at=excluded.updated_at,
                      window_started_at=excluded.window_started_at
                    """,
                    (
                        "user",
                        user_id,
                        int(plan["quota_limit"]),
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()

        return {
            "code": str(plan["code"]),
            "name": str(plan["name"]),
            "version": int(plan["version"]),
            "quota_mode": str(plan["quota_mode"]),
            "quota_limit": int(plan["quota_limit"]),
        }

    def create_checkout_intent(
        self,
        *,
        plan_code: str,
        customer_name: str,
        customer_email: str,
        customer_whatsapp: str,
        customer_document: str | None = None,
        customer_notes: str | None = None,
    ) -> dict[str, str | int]:
        normalized_code = str(plan_code or "").strip().lower()
        clean_name = str(customer_name or "").strip()
        clean_email = str(customer_email or "").strip().lower()
        clean_whatsapp = str(customer_whatsapp or "").strip()
        clean_document = str(customer_document or "").strip()
        clean_notes = str(customer_notes or "").strip()
        if not normalized_code:
            raise ValueError("plan_code is required")
        if not clean_name or not clean_email or not clean_whatsapp:
            raise ValueError("name, email, and whatsapp are required")

        now_iso = self.now_provider().isoformat()
        intent_id = f"chk_{uuid4().hex[:16]}"
        with self._lock:
            with self._connect() as conn:
                plan = self._fetchone(
                    conn,
                    """
                    SELECT code, name, price_cents, currency, billing_period
                    FROM plan_versions
                    WHERE code = ? AND is_active = ? AND is_public = ?
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (normalized_code, self._true_value(), self._true_value()),
                )
                if plan is None:
                    raise ValueError("plan not found")
                self._execute(
                    conn,
                    """
                    INSERT INTO checkout_intents (
                      id,
                      created_at,
                      updated_at,
                      status,
                      plan_code,
                      plan_name,
                      price_cents,
                      currency,
                      billing_period,
                      customer_name,
                      customer_email,
                      customer_whatsapp,
                      customer_document,
                      customer_notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent_id,
                        now_iso,
                        now_iso,
                        "pending",
                        str(plan["code"]),
                        str(plan["name"]),
                        int(plan["price_cents"]),
                        str(plan["currency"]),
                        str(plan["billing_period"]),
                        clean_name,
                        clean_email,
                        clean_whatsapp,
                        clean_document or None,
                        clean_notes or None,
                    ),
                )
                conn.commit()
        return {
            "id": intent_id,
            "created_at": now_iso,
            "status": "pending",
            "plan_code": str(plan["code"]),
            "plan_name": str(plan["name"]),
            "price_cents": int(plan["price_cents"]),
            "currency": str(plan["currency"]),
            "billing_period": str(plan["billing_period"]),
            "customer_name": clean_name,
            "customer_email": clean_email,
            "customer_whatsapp": clean_whatsapp,
        }

    def _ensure_anonymous_identity(self, fingerprint: str) -> str:
        now = self.now_provider().isoformat()
        with self._lock:
            with self._connect() as conn:
                existing = self._fetchone(
                    conn,
                    "SELECT id FROM anonymous_identities WHERE fingerprint = ?",
                    (fingerprint,),
                )
                if existing is not None:
                    anon_id = str(existing["id"])
                    self._execute(
                        conn,
                        "UPDATE anonymous_identities SET last_seen_at = ? WHERE id = ?",
                        (now, anon_id),
                    )
                    conn.commit()
                    return anon_id
                anon_id = f"anon_{uuid4().hex[:12]}"
                self._execute(
                    conn,
                    """
                    INSERT INTO anonymous_identities (id, fingerprint, created_at, last_seen_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (anon_id, fingerprint, now, now),
                )
                conn.commit()
                return anon_id

    def _read_active_user_plan(self, *, user_id: str) -> dict[str, str | int] | None:
        with self._lock:
            with self._connect() as conn:
                row = self._fetchone(
                    conn,
                    """
                    SELECT
                      pv.code,
                      pv.name,
                      pv.version,
                      pv.quota_mode,
                      pv.quota_limit,
                      pv.quota_window_days,
                      pv.max_upload_size_bytes,
                      pv.max_pages_per_file
                    FROM user_plan_subscriptions ups
                    JOIN plan_versions pv ON pv.id = ups.plan_version_id
                    WHERE ups.user_id = ? AND ups.status = 'active'
                    ORDER BY pv.version DESC
                    LIMIT 1
                    """,
                    (user_id,),
                )
                if row is None:
                    return None
                return {
                    "code": str(row["code"]),
                    "name": str(row["name"]),
                    "version": int(row["version"]),
                    "quota_mode": str(row["quota_mode"]),
                    "quota_limit": int(row["quota_limit"]),
                    "quota_window_days": int(row["quota_window_days"]),
                    "max_upload_size_bytes": int(row["max_upload_size_bytes"]),
                    "max_pages_per_file": int(row["max_pages_per_file"]),
                }

    def _read_usage(self, identity: IdentityContext) -> dict[str, int | datetime]:
        with self._lock:
            with self._connect() as conn:
                now = self.now_provider()
                row = self._fetchone(
                    conn,
                    """
                    SELECT used_count, quota_limit, updated_at, window_started_at
                    FROM usage
                    WHERE identity_type = ? AND identity_id = ?
                    """,
                    (identity.identity_type, identity.identity_id),
                )
                if row is None:
                    started_at = now.isoformat()
                    self._execute(
                        conn,
                        """
                        INSERT INTO usage (
                            identity_type,
                            identity_id,
                            used_count,
                            quota_limit,
                            updated_at,
                            window_started_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            identity.identity_type,
                            identity.identity_id,
                            0,
                            identity.quota_limit,
                            started_at,
                            started_at,
                        ),
                    )
                    conn.commit()
                    return {"used_count": 0, "window_started_at": now}

                used_count = int(row["used_count"] or 0)
                window_started_at = self._parse_usage_datetime(
                    str(row["window_started_at"] or row["updated_at"] or now.isoformat()),
                    fallback=now,
                )

                if self._is_quota_window_expired(window_started_at, now, quota_window_days=identity.quota_window_days):
                    window_started_at = now
                    used_count = 0
                    started_at = window_started_at.isoformat()
                    self._execute(
                        conn,
                        """
                        UPDATE usage
                        SET used_count = ?, quota_limit = ?, updated_at = ?, window_started_at = ?
                        WHERE identity_type = ? AND identity_id = ?
                        """,
                        (
                            used_count,
                            identity.quota_limit,
                            started_at,
                            started_at,
                            identity.identity_type,
                            identity.identity_id,
                        ),
                    )
                    conn.commit()

                return {"used_count": used_count, "window_started_at": window_started_at}

    def _hash_password(self, password: str, salt: str) -> str:
        derived_key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            PASSWORD_HASH_ITERATIONS,
        )
        return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${base64.b64encode(derived_key).decode('ascii')}"

    def _verify_password(self, password: str, stored_hash: str, stored_salt: str) -> bool:
        if not stored_hash or not stored_salt:
            return False
        expected_hash = self._hash_password(password=password, salt=stored_salt)
        return hmac.compare_digest(expected_hash, stored_hash)

    def _encode_token(self, user_id: str) -> str:
        payload = base64.urlsafe_b64encode(user_id.encode("utf-8")).decode("utf-8").rstrip("=")
        signature = hmac.new(self.token_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
        return f"{payload}.{signature}"

    def _decode_token(self, token: str) -> str:
        try:
            payload, signature = token.split(".", 1)
            expected = hmac.new(self.token_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
            if not hmac.compare_digest(expected, signature):
                raise InvalidUserTokenError
            padded_payload = payload + "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(padded_payload.encode("utf-8")).decode("utf-8")
            if not decoded.startswith("usr_"):
                raise InvalidUserTokenError
            return decoded
        except (ValueError, UnicodeDecodeError):
            raise InvalidUserTokenError from None

    def _user_exists(self, user_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = self._fetchone(conn, "SELECT id FROM users WHERE id = ?", (user_id,))
                return row is not None

    def _connect(self) -> sqlite3.Connection:
        if self._use_postgres:
            assert psycopg is not None and dict_row is not None
            conn = psycopg.connect(self.database_url, row_factory=dict_row)
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self.database_schema}", public')
            return conn
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        if self._use_postgres:
            self._init_postgres_db()
            return

        with self._lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        password_salt TEXT NOT NULL,
                        auth_provider TEXT NOT NULL DEFAULT 'local',
                        provider_user_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS anonymous_identities (
                        id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS usage (
                        identity_type TEXT NOT NULL,
                        identity_id TEXT NOT NULL,
                        used_count INTEGER NOT NULL,
                        quota_limit INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        window_started_at TEXT,
                        PRIMARY KEY (identity_type, identity_id)
                    );

                    CREATE TABLE IF NOT EXISTS user_conversions (
                        analysis_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT,
                        filename TEXT NOT NULL,
                        model TEXT NOT NULL,
                        conversion_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        transactions_count INTEGER NOT NULL DEFAULT 0,
                        pages_count INTEGER,
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    );

                    CREATE TABLE IF NOT EXISTS google_oauth_states (
                        state TEXT PRIMARY KEY,
                        code_verifier TEXT NOT NULL,
                        next_path TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS plan_versions (
                        id TEXT PRIMARY KEY,
                        code TEXT NOT NULL,
                        name TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        currency TEXT NOT NULL,
                        price_cents INTEGER NOT NULL,
                        billing_period TEXT NOT NULL,
                        quota_mode TEXT NOT NULL,
                        quota_limit INTEGER NOT NULL,
                        quota_window_days INTEGER NOT NULL,
                        max_upload_size_bytes INTEGER NOT NULL,
                        max_pages_per_file INTEGER NOT NULL,
                        is_public INTEGER NOT NULL DEFAULT 1,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS user_plan_subscriptions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        plan_version_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(plan_version_id) REFERENCES plan_versions(id)
                    );

                    CREATE TABLE IF NOT EXISTS checkout_intents (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        plan_code TEXT NOT NULL,
                        plan_name TEXT NOT NULL,
                        price_cents INTEGER NOT NULL,
                        currency TEXT NOT NULL,
                        billing_period TEXT NOT NULL,
                        customer_name TEXT NOT NULL,
                        customer_email TEXT NOT NULL,
                        customer_whatsapp TEXT NOT NULL,
                        customer_document TEXT,
                        customer_notes TEXT
                    );
                    """
                )

                user_columns = {
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info(users)").fetchall()
                }
                if "auth_provider" not in user_columns:
                    conn.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'local'")
                if "provider_user_id" not in user_columns:
                    conn.execute("ALTER TABLE users ADD COLUMN provider_user_id TEXT")
                conn.execute(
                    """
                    UPDATE users
                    SET auth_provider = 'local'
                    WHERE auth_provider IS NULL OR auth_provider = ''
                    """
                )
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_provider_user_id
                    ON users(provider_user_id)
                    WHERE auth_provider = 'google' AND provider_user_id IS NOT NULL
                    """
                )

                usage_columns = {
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info(usage)").fetchall()
                }
                user_conversions_columns = {
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info(user_conversions)").fetchall()
                }
                if "window_started_at" not in usage_columns:
                    conn.execute("ALTER TABLE usage ADD COLUMN window_started_at TEXT")
                if "pages_count" not in user_conversions_columns:
                    conn.execute("ALTER TABLE user_conversions ADD COLUMN pages_count INTEGER")
                conn.execute(
                    """
                    UPDATE usage
                    SET window_started_at = updated_at
                    WHERE window_started_at IS NULL OR window_started_at = ''
                    """
                )
                self._seed_default_plans_sqlite(conn)
                self._apply_default_plan_prices_sqlite(conn)
                conn.commit()

    def _init_postgres_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.database_schema}"')
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS users (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            email TEXT NOT NULL UNIQUE,
                            password_hash TEXT NOT NULL,
                            password_salt TEXT NOT NULL,
                            auth_provider TEXT NOT NULL DEFAULT 'local',
                            provider_user_id TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS anonymous_identities (
                            id TEXT PRIMARY KEY,
                            fingerprint TEXT NOT NULL UNIQUE,
                            created_at TEXT NOT NULL,
                            last_seen_at TEXT NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS usage (
                            identity_type TEXT NOT NULL,
                            identity_id TEXT NOT NULL,
                            used_count INTEGER NOT NULL,
                            quota_limit INTEGER NOT NULL,
                            updated_at TEXT NOT NULL,
                            window_started_at TEXT,
                            PRIMARY KEY (identity_type, identity_id)
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS user_conversions (
                            analysis_id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            expires_at TEXT,
                            filename TEXT NOT NULL,
                            model TEXT NOT NULL,
                            conversion_type TEXT NOT NULL,
                            status TEXT NOT NULL,
                            transactions_count INTEGER NOT NULL DEFAULT 0,
                            pages_count INTEGER,
                            FOREIGN KEY(user_id) REFERENCES users(id)
                        )
                        """
                    )
                    cur.execute(
                        """
                        ALTER TABLE user_conversions
                        ADD COLUMN IF NOT EXISTS pages_count INTEGER
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS google_oauth_states (
                            state TEXT PRIMARY KEY,
                            code_verifier TEXT NOT NULL,
                            next_path TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            expires_at TEXT NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS plan_versions (
                            id TEXT PRIMARY KEY,
                            code TEXT NOT NULL,
                            name TEXT NOT NULL,
                            version INTEGER NOT NULL,
                            currency TEXT NOT NULL,
                            price_cents INTEGER NOT NULL,
                            billing_period TEXT NOT NULL,
                            quota_mode TEXT NOT NULL,
                            quota_limit INTEGER NOT NULL,
                            quota_window_days INTEGER NOT NULL,
                            max_upload_size_bytes INTEGER NOT NULL,
                            max_pages_per_file INTEGER NOT NULL,
                            is_public BOOLEAN NOT NULL DEFAULT TRUE,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS user_plan_subscriptions (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            plan_version_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            started_at TEXT NOT NULL,
                            ended_at TEXT,
                            FOREIGN KEY(user_id) REFERENCES users(id),
                            FOREIGN KEY(plan_version_id) REFERENCES plan_versions(id)
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS checkout_intents (
                            id TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            status TEXT NOT NULL,
                            plan_code TEXT NOT NULL,
                            plan_name TEXT NOT NULL,
                            price_cents INTEGER NOT NULL,
                            currency TEXT NOT NULL,
                            billing_period TEXT NOT NULL,
                            customer_name TEXT NOT NULL,
                            customer_email TEXT NOT NULL,
                            customer_whatsapp TEXT NOT NULL,
                            customer_document TEXT,
                            customer_notes TEXT
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_provider_user_id
                        ON users(provider_user_id)
                        WHERE auth_provider = 'google' AND provider_user_id IS NOT NULL
                        """
                    )
                    cur.execute(
                        """
                        UPDATE users
                        SET auth_provider = 'local'
                        WHERE auth_provider IS NULL OR auth_provider = ''
                        """
                    )
                    cur.execute(
                        """
                        UPDATE usage
                        SET window_started_at = updated_at
                        WHERE window_started_at IS NULL OR window_started_at = ''
                        """
                    )
                    self._seed_default_plans_postgres(conn)
                    self._apply_default_plan_prices_postgres(conn)
                conn.commit()

    def _seed_default_plans_sqlite(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute("SELECT COUNT(*) AS cnt FROM plan_versions").fetchone()
        if existing is not None and int(existing["cnt"] or 0) > 0:
            return
        now_iso = self.now_provider().isoformat()
        for code, name, version, currency, price_cents, quota_limit in DEFAULT_PUBLIC_PLANS:
            conn.execute(
                """
                INSERT INTO plan_versions (
                  id,
                  code,
                  name,
                  version,
                  currency,
                  price_cents,
                  billing_period,
                  quota_mode,
                  quota_limit,
                  quota_window_days,
                  max_upload_size_bytes,
                  max_pages_per_file,
                  is_public,
                  is_active,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"plan_{code}_v{version}",
                    code,
                    name,
                    version,
                    currency,
                    price_cents,
                    "monthly",
                    "pages",
                    quota_limit,
                    MONTHLY_QUOTA_WINDOW_DAYS,
                    PAID_MAX_UPLOAD_SIZE_BYTES,
                    PAID_MAX_PAGES_PER_FILE,
                    1,
                    1,
                    now_iso,
                ),
            )

    def _apply_default_plan_prices_sqlite(self, conn: sqlite3.Connection) -> None:
        for code, _name, _version, _currency, price_cents, _quota_limit in DEFAULT_PUBLIC_PLANS:
            conn.execute(
                """
                UPDATE plan_versions
                SET price_cents = ?
                WHERE code = ? AND is_active = ? AND is_public = ?
                """,
                (price_cents, code, self._true_value(), self._true_value()),
            )

    def _seed_default_plans_postgres(self, conn) -> None:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) AS cnt FROM plan_versions")
            existing = cur.fetchone()
            if existing is not None and int(existing["cnt"] or 0) > 0:
                return
            now_iso = self.now_provider().isoformat()
            for code, name, version, currency, price_cents, quota_limit in DEFAULT_PUBLIC_PLANS:
                cur.execute(
                    """
                    INSERT INTO plan_versions (
                      id,
                      code,
                      name,
                      version,
                      currency,
                      price_cents,
                      billing_period,
                      quota_mode,
                      quota_limit,
                      quota_window_days,
                      max_upload_size_bytes,
                      max_pages_per_file,
                      is_public,
                      is_active,
                      created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        f"plan_{code}_v{version}",
                        code,
                        name,
                        version,
                        currency,
                        price_cents,
                        "monthly",
                        "pages",
                        quota_limit,
                        MONTHLY_QUOTA_WINDOW_DAYS,
                        PAID_MAX_UPLOAD_SIZE_BYTES,
                        PAID_MAX_PAGES_PER_FILE,
                        True,
                        True,
                        now_iso,
                    ),
                )
        finally:
            cur.close()

    def _apply_default_plan_prices_postgres(self, conn) -> None:
        cur = conn.cursor()
        try:
            for code, _name, _version, _currency, price_cents, _quota_limit in DEFAULT_PUBLIC_PLANS:
                cur.execute(
                    """
                    UPDATE plan_versions
                    SET price_cents = %s
                    WHERE code = %s AND is_active = %s AND is_public = %s
                    """,
                    (price_cents, code, self._true_value(), self._true_value()),
                )
        finally:
            cur.close()

    def _is_expired(self, expires_at_raw: str, now: datetime) -> bool:
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except ValueError:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at < now

    def _is_quota_window_expired(self, window_started_at: datetime, now: datetime, *, quota_window_days: int) -> bool:
        return now >= (window_started_at + timedelta(days=max(1, int(quota_window_days))))

    def _parse_usage_datetime(self, raw_value: str, fallback: datetime) -> datetime:
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return fallback
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _normalize_next_path(self, next_path: str | None) -> str:
        raw = str(next_path or "").strip()
        if not raw.startswith("/"):
            return "/client-area.html"
        return raw

    def _adapt_query(self, query: str) -> str:
        if self._use_postgres:
            return query.replace("?", "%s")
        return query

    def _true_value(self):
        if self._use_postgres:
            return True
        return 1

    def _execute(self, conn, query: str, params: tuple = ()):
        adapted = self._adapt_query(query)
        if self._use_postgres:
            cur = conn.cursor()
            cur.execute(adapted, params)
            return cur
        return conn.execute(adapted, params)

    def _fetchone(self, conn, query: str, params: tuple = ()):
        cur = self._execute(conn, query, params)
        if self._use_postgres:
            try:
                return cur.fetchone()
            finally:
                cur.close()
        return cur.fetchone()

    def _fetchall(self, conn, query: str, params: tuple = ()):
        cur = self._execute(conn, query, params)
        if self._use_postgres:
            try:
                return cur.fetchall()
            finally:
                cur.close()
        return cur.fetchall()

    def _normalize_database_schema(self, schema: str | None) -> str:
        raw = (schema or "public").strip()
        if not raw:
            return "public"
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
            raise RuntimeError("DATABASE_SCHEMA must be a valid PostgreSQL schema name.")
        return raw
