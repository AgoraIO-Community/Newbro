from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, Response, WebSocket
from pydantic import BaseModel

from newbro.config_home import SYNAPSE_HOME_DIR
from newbro.protocol import Persona


PUBLIC_AUTH_DB = SYNAPSE_HOME_DIR / "public_auth.sqlite3"
SESSION_COOKIE_NAME = "newbro_session"
SIGNUP_INVITE_CODE_ENV = "NEWBRO_SIGNUP_INVITE_CODE"
LEGACY_DRAFT_BASE_PROMPT = "Help turn voice instructions into clear executable drafts."
DEFAULT_BRO_BASE_PROMPT = (
    "You are the selected local execution Bro. Execute the user's direct typed "
    "or push-to-talk instructions in the connected workspace, and ask only when "
    "you need a concrete decision to continue."
)

USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USER_CODE_LENGTH = 4
DEVICE_PAIRING_TTL_SECONDS = 600
DEVICE_PAIRING_POLL_INTERVAL_SECONDS = 2


class PublicUser(BaseModel):
    user_id: str
    email: str | None = None


class PublicPersonaRecord(BaseModel):
    persona_id: str
    name: str
    avatar: str = "bro"
    base_prompt: str = ""
    executor_node_id: str | None = None
    bro_detail_session_id: str

    def to_persona(self) -> Persona:
        return Persona(
            persona_id=self.persona_id,
            name=self.name,
            avatar=self.avatar,
            base_prompt=self.base_prompt,
            executor_node_id=self.executor_node_id,
            bro_detail_session_id=self.bro_detail_session_id,
        )


@dataclass(slots=True)
class RedeemedSession:
    user: PublicUser
    raw_token: str


@dataclass(slots=True)
class DevicePairingStart:
    device_code: str
    user_code: str
    interval: int
    expires_at: str


@dataclass(slots=True)
class DevicePairingPoll:
    status: str  # "pending" | "claimed"
    token: str | None = None


class PublicAuthStore:
    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path or PUBLIC_AUTH_DB
        self._lock = asyncio.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # `with conn:` only manages the transaction (commit/rollback); it does NOT
        # close the connection. Closing in `finally` releases the file descriptor
        # deterministically instead of leaking it until cycle-GC reaps the
        # Connection/Cursor reference cycle -- which under load exhausts the
        # worker's open-file limit and surfaces as "unable to open database file".
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS invites (
                    code_hash TEXT PRIMARY KEY,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    redeemed_by TEXT,
                    redeemed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_owners (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS personas (
                    user_id TEXT NOT NULL,
                    persona_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    avatar TEXT NOT NULL,
                    base_prompt TEXT NOT NULL,
                    executor_node_id TEXT,
                    bro_detail_session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, persona_id)
                );
                CREATE TABLE IF NOT EXISTS executor_node_owners (
                    node_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_pairings (
                    device_code_hash TEXT PRIMARY KEY,
                    user_code TEXT NOT NULL UNIQUE,
                    user_id TEXT,
                    issued_token TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    claimed_at TEXT
                );
                """
            )
            try:
                conn.execute(
                    "UPDATE personas SET base_prompt = ? WHERE base_prompt = ?",
                    (DEFAULT_BRO_BASE_PROMPT, LEGACY_DRAFT_BASE_PROMPT),
                )
            except sqlite3.OperationalError as exc:
                if "readonly" not in str(exc).lower():
                    raise

    async def create_invite(self, code: str, *, email: str | None = None) -> None:
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO invites (code_hash, email, created_at, redeemed_by, redeemed_at)
                    VALUES (?, ?, ?, NULL, NULL)
                    """,
                    (_hash_secret(code), _normalize_email(email), _timestamp()),
                )

    async def signup_with_fixed_code(self, *, email: str, code: str) -> RedeemedSession:
        normalized_email = _normalize_email(email)
        if not normalized_email:
            raise PublicAuthError("Email is required.")
        normalized_code = code.strip()
        if not normalized_code:
            raise PublicAuthError("Invitation code is required.")
        expected_code = os.getenv(SIGNUP_INVITE_CODE_ENV, "").strip()
        if not expected_code:
            raise PublicAuthError("Self-signup is not configured.")
        if not hmac.compare_digest(normalized_code, expected_code):
            raise PublicAuthError("Invalid invitation code.")
        async with self._lock:
            return self._create_user_session(email=normalized_email)

    async def redeem_invite(self, code: str) -> RedeemedSession:
        normalized = code.strip()
        if not normalized:
            raise PublicAuthError("Invite code is required.")
        code_hash = _hash_secret(normalized)
        async with self._lock:
            with self._connect() as conn:
                invite = conn.execute(
                    "SELECT * FROM invites WHERE code_hash = ?",
                    (code_hash,),
                ).fetchone()
                if invite is None:
                    raise PublicAuthError("Invalid invite code.")
                existing_user_id = invite["redeemed_by"]
                now = _timestamp()
                if existing_user_id:
                    user = conn.execute(
                        "SELECT * FROM users WHERE user_id = ?",
                        (existing_user_id,),
                    ).fetchone()
                    if user is None:
                        raise PublicAuthError("Invite is invalid.")
                    conn.execute(
                        "UPDATE users SET last_seen_at = ? WHERE user_id = ?",
                        (now, existing_user_id),
                    )
                    public_user = _user_from_row(user)
                else:
                    user = _find_existing_user_for_email(conn, email=invite["email"])
                    if user is not None:
                        user_id = str(user["user_id"])
                        conn.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?", (now, user_id))
                        public_user = _user_from_row(user)
                    else:
                        user_id = f"user-{uuid4().hex[:12]}"
                        conn.execute(
                            "INSERT INTO users (user_id, email, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                            (user_id, invite["email"], now, now),
                        )
                        public_user = PublicUser(user_id=user_id, email=invite["email"])
                    conn.execute(
                        "UPDATE invites SET redeemed_by = ?, redeemed_at = ? WHERE code_hash = ?",
                        (user_id, now, code_hash),
                    )
                raw_token = secrets.token_urlsafe(32)
                conn.execute(
                    "INSERT INTO browser_sessions (token_hash, user_id, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                    (_hash_secret(raw_token), public_user.user_id, now, now),
                )
        return RedeemedSession(user=public_user, raw_token=raw_token)

    def _create_user_session(self, *, email: str | None) -> RedeemedSession:
        with self._connect() as conn:
            now = _timestamp()
            user = _find_existing_user_for_email(conn, email=email)
            if user is not None:
                public_user = _user_from_row(user)
                conn.execute(
                    "UPDATE users SET last_seen_at = ? WHERE user_id = ?",
                    (now, public_user.user_id),
                )
            else:
                user_id = f"user-{uuid4().hex[:12]}"
                public_user = PublicUser(user_id=user_id, email=email)
                conn.execute(
                    "INSERT INTO users (user_id, email, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                    (user_id, email, now, now),
                )
            raw_token = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO browser_sessions (token_hash, user_id, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                (_hash_secret(raw_token), public_user.user_id, now, now),
            )
        return RedeemedSession(user=public_user, raw_token=raw_token)

    async def user_for_token(self, raw_token: str | None) -> PublicUser | None:
        if not raw_token:
            return None
        token_hash = _hash_secret(raw_token)
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT users.* FROM browser_sessions
                    JOIN users ON users.user_id = browser_sessions.user_id
                    WHERE browser_sessions.token_hash = ?
                    """,
                    (token_hash,),
                ).fetchone()
                if row is None:
                    return None
                now = _timestamp()
                conn.execute(
                    "UPDATE browser_sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_hash),
                )
                conn.execute(
                    "UPDATE users SET last_seen_at = ? WHERE user_id = ?",
                    (now, row["user_id"]),
                )
                return _user_from_row(row)

    async def delete_browser_session(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        async with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM browser_sessions WHERE token_hash = ?", (_hash_secret(raw_token),))

    async def create_device_pairing(self) -> DevicePairingStart:
        async with self._lock:
            with self._connect() as conn:
                now = datetime.now(UTC)
                expires_at = (now + timedelta(seconds=DEVICE_PAIRING_TTL_SECONDS)).isoformat()
                device_code = secrets.token_urlsafe(32)
                for _ in range(10):
                    user_code = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))
                    try:
                        conn.execute(
                            """
                            INSERT INTO device_pairings
                                (device_code_hash, user_code, status, created_at, expires_at)
                            VALUES (?, ?, 'pending', ?, ?)
                            """,
                            (_hash_secret(device_code), user_code, now.isoformat(), expires_at),
                        )
                        break
                    except sqlite3.IntegrityError:
                        continue
                else:
                    raise PublicAuthError("Could not allocate a pairing code.")
        return DevicePairingStart(
            device_code=device_code,
            user_code=user_code,
            interval=DEVICE_PAIRING_POLL_INTERVAL_SECONDS,
            expires_at=expires_at,
        )

    async def claim_session(self, *, user_id: str, session_id: str) -> None:
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO session_owners (session_id, user_id, created_at) VALUES (?, ?, ?)",
                    (session_id, user_id, _timestamp()),
                )

    async def user_owns_session(self, *, user_id: str, session_id: str) -> bool:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM session_owners WHERE session_id = ? AND user_id = ?",
                    (session_id, user_id),
                ).fetchone()
                return row is not None

    async def owned_session_ids(self, *, user_id: str) -> list[str]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT session_id FROM session_owners WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
        return [str(row["session_id"]) for row in rows]

    async def list_personas(self, *, user_id: str) -> list[Persona]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM personas WHERE user_id = ? ORDER BY lower(name), persona_id",
                    (user_id,),
                ).fetchall()
        return [_persona_from_row(row).to_persona() for row in rows]

    async def create_persona(
        self,
        *,
        user_id: str,
        name: str,
        avatar: str,
        base_prompt: str,
        executor_node_id: str | None = None,
    ) -> Persona:
        record = PublicPersonaRecord(
            persona_id=_generated_persona_id(name),
            name=name.strip(),
            avatar=avatar,
            base_prompt=base_prompt,
            executor_node_id=executor_node_id,
            bro_detail_session_id=_generated_bro_detail_session_id(),
        )
        if not record.name:
            raise PublicAuthError("Persona name is required.")
        now = _timestamp()
        async with self._lock:
            with self._connect() as conn:
                if record.executor_node_id is not None:
                    existing = conn.execute(
                        """
                        SELECT * FROM personas
                        WHERE user_id = ? AND executor_node_id = ?
                        ORDER BY created_at, persona_id
                        LIMIT 1
                        """,
                        (user_id, record.executor_node_id),
                    ).fetchone()
                    if existing is not None:
                        existing_record = _persona_from_row(existing)
                        if existing_record.base_prompt == LEGACY_DRAFT_BASE_PROMPT:
                            updated = existing_record.model_copy(update={"base_prompt": DEFAULT_BRO_BASE_PROMPT})
                            conn.execute(
                                """
                                UPDATE personas
                                SET base_prompt = ?, updated_at = ?
                                WHERE user_id = ? AND persona_id = ?
                                """,
                                (updated.base_prompt, _timestamp(), user_id, updated.persona_id),
                            )
                            return updated.to_persona()
                        return existing_record.to_persona()
                conn.execute(
                    """
                    INSERT INTO personas
                    (user_id, persona_id, name, avatar, base_prompt, executor_node_id, bro_detail_session_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        record.persona_id,
                        record.name,
                        record.avatar,
                        record.base_prompt,
                        record.executor_node_id,
                        record.bro_detail_session_id,
                        now,
                        now,
                    ),
                )
        return record.to_persona()

    async def update_persona(
        self,
        *,
        user_id: str,
        persona_id: str,
        updates: dict[str, Any],
    ) -> Persona:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM personas WHERE user_id = ? AND persona_id = ?",
                    (user_id, persona_id),
                ).fetchone()
                if row is None:
                    raise KeyError(persona_id)
                current = _persona_from_row(row)
                updated = current.model_copy(update=updates)
                if not updated.name.strip():
                    raise PublicAuthError("Persona name is required.")
                conn.execute(
                    """
                    UPDATE personas
                    SET name = ?, avatar = ?, base_prompt = ?, executor_node_id = ?, bro_detail_session_id = ?, updated_at = ?
                    WHERE user_id = ? AND persona_id = ?
                    """,
                    (
                        updated.name.strip(),
                        updated.avatar,
                        updated.base_prompt,
                        updated.executor_node_id,
                        updated.bro_detail_session_id,
                        _timestamp(),
                        user_id,
                        persona_id,
                    ),
                )
                return updated.to_persona()

    async def delete_persona(self, *, user_id: str, persona_id: str) -> bool:
        async with self._lock:
            with self._connect() as conn:
                result = conn.execute(
                    "DELETE FROM personas WHERE user_id = ? AND persona_id = ?",
                    (user_id, persona_id),
                )
                return result.rowcount > 0

    async def ensure_default_persona(self, *, user_id: str) -> Persona:
        personas = await self.list_personas(user_id=user_id)
        if personas:
            return personas[0]
        return await self.create_persona(
            user_id=user_id,
            name="Newbro",
            avatar="bro",
            base_prompt=DEFAULT_BRO_BASE_PROMPT,
        )

    async def claim_executor_node(self, *, user_id: str, node_id: str) -> None:
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO executor_node_owners (node_id, user_id, created_at) VALUES (?, ?, ?)",
                    (node_id, user_id, _timestamp()),
                )

    async def user_owns_executor_node(self, *, user_id: str, node_id: str) -> bool:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM executor_node_owners WHERE node_id = ? AND user_id = ?",
                    (node_id, user_id),
                ).fetchone()
                return row is not None

    async def owned_executor_node_ids(self, *, user_id: str) -> set[str]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT node_id FROM executor_node_owners WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
        return {str(row["node_id"]) for row in rows}


class PublicAuthError(RuntimeError):
    pass


async def require_public_user(request: Request) -> PublicUser:
    store: PublicAuthStore = request.app.state.public_auth_store
    user = await store.user_for_token(request.cookies.get(SESSION_COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


async def require_session_owner(request: Request, session_id: str) -> PublicUser:
    user = await require_public_user(request)
    store: PublicAuthStore = request.app.state.public_auth_store
    if not await store.user_owns_session(user_id=user.user_id, session_id=session_id):
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return user


def is_internal_connector_request(request: Request) -> bool:
    expected = getattr(request.app.state.runtime_container.settings, "connector_internal_token", None)
    if not expected:
        return False
    supplied = request.headers.get("X-Newbro-Connector-Token")
    return supplied is not None and hmac.compare_digest(supplied, expected)


async def require_session_owner_or_internal(request: Request, session_id: str) -> PublicUser | None:
    if is_internal_connector_request(request):
        return None
    return await require_session_owner(request, session_id)


async def user_for_websocket(websocket: WebSocket) -> PublicUser | None:
    store: PublicAuthStore = websocket.app.state.public_auth_store
    return await store.user_for_token(websocket.cookies.get(SESSION_COOKIE_NAME))


def set_public_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_public_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cookie_secure() -> bool:
    return os.getenv("SYNAPSE_PUBLIC_COOKIE_SECURE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_email(value: str | None) -> str | None:
    cleaned = value.strip().lower() if value else ""
    return cleaned or None


def _find_existing_user_for_email(conn: sqlite3.Connection, *, email: str | None) -> sqlite3.Row | None:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return None
    return conn.execute(
        """
        SELECT users.*
        FROM users
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS persona_count
            FROM personas
            GROUP BY user_id
        ) persona_counts ON persona_counts.user_id = users.user_id
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS node_count
            FROM executor_node_owners
            GROUP BY user_id
        ) node_counts ON node_counts.user_id = users.user_id
        WHERE lower(users.email) = ?
        ORDER BY
            (COALESCE(persona_counts.persona_count, 0) + COALESCE(node_counts.node_count, 0)) DESC,
            users.last_seen_at DESC,
            users.created_at DESC,
            users.user_id ASC
        LIMIT 1
        """,
        (normalized_email,),
    ).fetchone()


def _user_from_row(row: sqlite3.Row) -> PublicUser:
    return PublicUser(user_id=str(row["user_id"]), email=row["email"])


def _persona_from_row(row: sqlite3.Row) -> PublicPersonaRecord:
    return PublicPersonaRecord(
        persona_id=str(row["persona_id"]),
        name=str(row["name"]),
        avatar=str(row["avatar"]),
        base_prompt=str(row["base_prompt"]),
        executor_node_id=row["executor_node_id"],
        bro_detail_session_id=str(row["bro_detail_session_id"]),
    )


def _generated_persona_id(name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
    return f"persona-{slug or 'bro'}-{uuid4().hex[:8]}"


def _generated_bro_detail_session_id() -> str:
    return f"bro-detail-{uuid4().hex[:8]}"
