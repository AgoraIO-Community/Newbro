from __future__ import annotations

from newbro.api.public_auth import PublicAuthStore, PublicUser
from newbro.runtime.models import SessionSnapshot, SessionStreamEventBase, SnapshotStreamEvent


async def scope_session_snapshot_for_user(
    store: PublicAuthStore,
    user: PublicUser,
    snapshot: SessionSnapshot,
) -> SessionSnapshot:
    owned_node_ids = await store.owned_executor_node_ids(user_id=user.user_id)
    return snapshot.model_copy(
        update={
            "executor_nodes": [
                node
                for node in snapshot.executor_nodes
                if node.node_id in owned_node_ids
            ],
        }
    )


async def scope_stream_event_for_user(
    store: PublicAuthStore,
    user: PublicUser,
    event: SessionStreamEventBase,
) -> SessionStreamEventBase:
    if not isinstance(event, SnapshotStreamEvent):
        return event
    return event.model_copy(
        update={
            "snapshot": await scope_session_snapshot_for_user(store, user, event.snapshot),
        }
    )
