from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from newbro.config_home import SYNAPSE_HOME_DIR
from newbro.protocol import ExecutorNodeCredentialIssue, ExecutorNodeExecutor, ExecutorNodeRecord
from newbro.yaml_support import YAMLParseError, load_yaml_file


EXECUTOR_NODES_FILE = SYNAPSE_HOME_DIR / "executor_nodes.yaml"


class ExecutorNodeRegistryError(RuntimeError):
    pass


class StoredExecutorNodeRecord(BaseModel):
    node_id: str
    name: str
    enabled_executors: list[str] = Field(default_factory=list)
    acpx_agent: str | None = None
    raw_token: str | None = None
    token_hash: str
    token_hint: str
    last_connected_at: str | None = None
    last_seen_at: str | None = None


@dataclass(slots=True)
class ExecutorNodeConnectionView:
    connected: bool
    executors: list[str]
    executor_capabilities: list[ExecutorNodeExecutor] = field(default_factory=list)


class ExecutorNodeRegistry:
    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path or EXECUTOR_NODES_FILE
        self._lock = asyncio.Lock()
        self._records: dict[str, StoredExecutorNodeRecord] = {
            record.node_id: record for record in _load_records(self._path)
        }

    async def list_records(
        self,
        connections: dict[str, ExecutorNodeConnectionView] | None = None,
    ) -> list[ExecutorNodeRecord]:
        async with self._lock:
            stored = [record.model_copy(deep=True) for record in self._records.values()]
        merged = [
            _public_record(
                record,
                connection=(connections or {}).get(record.node_id),
            )
            for record in sorted(stored, key=lambda item: (item.name.lower(), item.node_id))
        ]
        return merged

    async def get_record(self, node_id: str) -> StoredExecutorNodeRecord | None:
        async with self._lock:
            record = self._records.get(node_id)
            return record.model_copy(deep=True) if record is not None else None

    async def has_node(self, node_id: str) -> bool:
        async with self._lock:
            return node_id in self._records

    async def create_node(
        self,
        *,
        name: str,
        enabled_executors: list[str],
        acpx_agent: str | None = None,
    ) -> ExecutorNodeCredentialIssue:
        normalized_name = name.strip()
        normalized_executors = _normalize_executor_list(enabled_executors)
        normalized_acpx_agent = _normalize_optional_text(acpx_agent)
        if not normalized_name:
            raise ExecutorNodeRegistryError("Executor node name is required.")
        if not normalized_executors:
            raise ExecutorNodeRegistryError("Executor node must enable exactly one executor family.")
        if len(normalized_executors) > 1:
            raise ExecutorNodeRegistryError("Executor node must choose exactly one executor family.")
        if "acpx" in normalized_executors and not normalized_acpx_agent:
            normalized_acpx_agent = "codex"
        node_id = f"node-{uuid4().hex[:8]}"
        token = secrets.token_urlsafe(24)
        record = StoredExecutorNodeRecord(
            node_id=node_id,
            name=normalized_name,
            enabled_executors=normalized_executors,
            acpx_agent=normalized_acpx_agent,
            raw_token=token,
            token_hash=_hash_token(token),
            token_hint=_hint(token),
        )
        async with self._lock:
            self._records[node_id] = record
            self._persist_locked()
        return ExecutorNodeCredentialIssue(
            node=_public_record(record),
            token=token,
        )

    async def update_node(
        self,
        node_id: str,
        *,
        name: str | None = None,
        enabled_executors: list[str] | None = None,
        acpx_agent: str | None = None,
        connection: ExecutorNodeConnectionView | None = None,
    ) -> ExecutorNodeRecord:
        async with self._lock:
            record = self._records.get(node_id)
            if record is None:
                raise ExecutorNodeRegistryError(f"Executor node '{node_id}' not found.")
            updates: dict[str, object] = {}
            if name is not None:
                normalized_name = name.strip()
                if not normalized_name:
                    raise ExecutorNodeRegistryError("Executor node name is required.")
                updates["name"] = normalized_name
            if enabled_executors is not None:
                normalized_executors = _normalize_executor_list(enabled_executors)
                if not normalized_executors:
                    raise ExecutorNodeRegistryError("Executor node must enable exactly one executor family.")
                if len(normalized_executors) > 1:
                    raise ExecutorNodeRegistryError("Executor node must choose exactly one executor family.")
                updates["enabled_executors"] = normalized_executors
            if acpx_agent is not None:
                updates["acpx_agent"] = _normalize_optional_text(acpx_agent)
            updated = record.model_copy(update=updates) if updates else record
            if "acpx" in updated.enabled_executors and not updated.acpx_agent:
                updated = updated.model_copy(update={"acpx_agent": "codex"})
            if "acpx" not in updated.enabled_executors and updated.acpx_agent is not None:
                updated = updated.model_copy(update={"acpx_agent": None})
            self._records[node_id] = updated
            self._persist_locked()
        return _public_record(updated, connection=connection)

    async def rotate_credentials(
        self,
        node_id: str,
        *,
        connection: ExecutorNodeConnectionView | None = None,
    ) -> ExecutorNodeCredentialIssue:
        token = secrets.token_urlsafe(24)
        async with self._lock:
            record = self._records.get(node_id)
            if record is None:
                raise ExecutorNodeRegistryError(f"Executor node '{node_id}' not found.")
            updated = record.model_copy(
                update={
                    "raw_token": token,
                    "token_hash": _hash_token(token),
                    "token_hint": _hint(token),
                }
            )
            self._records[node_id] = updated
            self._persist_locked()
        return ExecutorNodeCredentialIssue(
            node=_public_record(updated, connection=connection),
            token=token,
        )

    async def delete_node(self, node_id: str) -> bool:
        async with self._lock:
            removed = self._records.pop(node_id, None)
            if removed is None:
                return False
            self._persist_locked()
            return True

    async def reveal_token(self, node_id: str) -> ExecutorNodeCredentialIssue:
        async with self._lock:
            record = self._records.get(node_id)
            if record is None:
                raise ExecutorNodeRegistryError(f"Executor node '{node_id}' not found.")
            if record.raw_token in (None, ""):
                raise ExecutorNodeRegistryError(
                    f"Executor node '{node_id}' uses legacy non-retrievable credentials. Rotate credentials first."
                )
            token = record.raw_token
            return ExecutorNodeCredentialIssue(
                node=_public_record(record),
                token=token,
            )

    async def verify_credentials(
        self,
        *,
        node_id: str,
        token: str,
    ) -> StoredExecutorNodeRecord | None:
        async with self._lock:
            record = self._records.get(node_id)
            if record is None:
                return None
            if not hmac.compare_digest(record.token_hash, _hash_token(token)):
                return None
            return record.model_copy(deep=True)

    async def note_connected(self, node_id: str) -> None:
        timestamp = _timestamp()
        async with self._lock:
            record = self._records.get(node_id)
            if record is None:
                return
            self._records[node_id] = record.model_copy(
                update={"last_connected_at": timestamp, "last_seen_at": timestamp}
            )
            self._persist_locked()

    async def note_seen(self, node_id: str) -> None:
        timestamp = _timestamp()
        async with self._lock:
            record = self._records.get(node_id)
            if record is None:
                return
            self._records[node_id] = record.model_copy(update={"last_seen_at": timestamp})
            self._persist_locked()

    def _persist_locked(self) -> None:
        _write_records(self._path, self._records.values())


def _normalize_executor_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hint(value: str) -> str:
    if len(value) <= 10:
        return value
    return f"{value[:4]}...{value[-4:]}"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _public_record(
    record: StoredExecutorNodeRecord,
    *,
    connection: ExecutorNodeConnectionView | None = None,
) -> ExecutorNodeRecord:
    return ExecutorNodeRecord(
        node_id=record.node_id,
        name=record.name,
        enabled_executors=list(record.enabled_executors),
        acpx_agent=record.acpx_agent,
        connected_executors=list(connection.executors) if connection is not None else [],
        connection_status="connected" if connection is not None and connection.connected else "disconnected",
        token_hint=record.token_hint,
        last_connected_at=record.last_connected_at,
        last_seen_at=record.last_seen_at,
        connected_executor_capabilities=(
            [executor.model_copy(deep=True) for executor in connection.executor_capabilities]
            if connection is not None
            else []
        ),
    )


def _load_records(path: Path) -> list[StoredExecutorNodeRecord]:
    if not path.exists():
        return []
    try:
        raw = load_yaml_file(path)
    except (OSError, YAMLParseError) as exc:
        raise ExecutorNodeRegistryError(f"Invalid executor node registry at {path}: {exc}") from exc
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ExecutorNodeRegistryError(f"Executor node registry root must be a mapping: {path}")
    raw_nodes = raw.get("executor_nodes") or []
    if not isinstance(raw_nodes, list):
        raise ExecutorNodeRegistryError(f"'executor_nodes' must be a list in {path}")
    records: list[StoredExecutorNodeRecord] = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise ExecutorNodeRegistryError(f"Executor node entry must be a mapping in {path}")
        try:
            records.append(StoredExecutorNodeRecord.model_validate(raw_node))
        except ValidationError as exc:
            raise ExecutorNodeRegistryError(f"Invalid executor node entry in {path}: {exc}") from exc
    return records


def _write_records(path: Path, records: Iterable[StoredExecutorNodeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["version: 1", "executor_nodes:"]
    ordered_records = sorted(records, key=lambda item: (item.name.lower(), item.node_id))
    for record in ordered_records:
        lines.append(f"  - node_id: {_yaml_quote(record.node_id)}")
        lines.append(f"    name: {_yaml_quote(record.name)}")
        lines.append("    enabled_executors:")
        for executor_type in record.enabled_executors:
            lines.append(f"      - {_yaml_quote(executor_type)}")
        lines.append(f"    acpx_agent: {_yaml_quote(record.acpx_agent) if record.acpx_agent else 'null'}")
        lines.append(f"    raw_token: {_yaml_quote(record.raw_token) if record.raw_token else 'null'}")
        lines.append(f"    token_hash: {_yaml_quote(record.token_hash)}")
        lines.append(f"    token_hint: {_yaml_quote(record.token_hint)}")
        lines.append(
            f"    last_connected_at: {_yaml_quote(record.last_connected_at) if record.last_connected_at else 'null'}"
        )
        lines.append(f"    last_seen_at: {_yaml_quote(record.last_seen_at) if record.last_seen_at else 'null'}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
