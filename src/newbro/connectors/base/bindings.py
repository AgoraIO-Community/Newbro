from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from newbro.protocol import AgoraVoiceEvent, RuntimeDecision

from .transport import NewbroConnectorTransport


@dataclass(slots=True)
class ActiveConnectorBinding:
    binding_id: str
    synapse_session_id: str
    runtime_session_id: str | None
    metadata: dict[str, object]
    task: asyncio.Task[None]


class DuplicateBindingError(RuntimeError):
    pass


class MissingRegistrationConfigError(RuntimeError):
    pass


class ConnectorSpeaker:
    async def speak(self, runtime_session_id: str, text: str) -> None:  # pragma: no cover - protocol-like
        raise NotImplementedError


class ConnectorBindingRegistry:
    def __init__(
        self,
        transport: NewbroConnectorTransport,
        speaker: ConnectorSpeaker,
    ) -> None:
        self._transport = transport
        self._speaker = speaker
        self._bindings: dict[str, ActiveConnectorBinding] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        *,
        synapse_session_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ActiveConnectorBinding:
        async with self._lock:
            resolved_session_id = synapse_session_id or await self._transport.create_session()
            if (
                synapse_session_id is not None
                and any(
                    binding.synapse_session_id == resolved_session_id
                    for binding in self._bindings.values()
                )
            ):
                raise DuplicateBindingError(
                    f"Newbro session '{resolved_session_id}' is already bound."
                )

            binding_id = f"binding-{uuid4().hex[:8]}"
            binding = ActiveConnectorBinding(
                binding_id=binding_id,
                synapse_session_id=resolved_session_id,
                runtime_session_id=None,
                metadata=dict(metadata or {}),
                task=asyncio.create_task(
                    self._watch_notifications(
                        synapse_session_id=resolved_session_id,
                        binding_id=binding_id,
                    )
                ),
            )
            self._bindings[binding_id] = binding
            return binding

    async def finalize(
        self,
        binding_id: str,
        *,
        runtime_session_id: str,
        metadata: dict[str, object] | None = None,
    ) -> ActiveConnectorBinding:
        async with self._lock:
            binding = self._bindings.get(binding_id)
            if binding is None:
                raise KeyError(f"Unknown connector binding: {binding_id}")
            if not runtime_session_id:
                raise MissingRegistrationConfigError(
                    "runtime_session_id is required for connector binding."
                )
            if any(
                candidate.binding_id != binding_id
                and candidate.runtime_session_id == runtime_session_id
                for candidate in self._bindings.values()
            ):
                raise DuplicateBindingError(
                    f"Runtime session '{runtime_session_id}' is already registered."
                )
            binding.runtime_session_id = runtime_session_id
            if metadata:
                binding.metadata.update(metadata)
            return binding

    async def unregister(self, binding_id: str) -> bool:
        async with self._lock:
            binding = self._bindings.pop(binding_id, None)
        if binding is None:
            return False
        binding.task.cancel()
        try:
            await binding.task
        except asyncio.CancelledError:
            pass
        return True

    async def close(self) -> None:
        binding_ids = list(self._bindings.keys())
        for binding_id in binding_ids:
            await self.unregister(binding_id)

    def get(self, binding_id: str) -> ActiveConnectorBinding | None:
        return self._bindings.get(binding_id)

    async def submit_agora_event(self, session_id: str, event: AgoraVoiceEvent) -> RuntimeDecision:
        return await self._transport.submit_agora_event(session_id, event)

    async def _watch_notifications(
        self,
        *,
        synapse_session_id: str,
        binding_id: str,
    ) -> None:
        try:
            async for text in self._transport.watch_notification_texts(synapse_session_id):
                binding = self._bindings.get(binding_id)
                if binding is None:
                    return
                if not binding.runtime_session_id:
                    continue
                try:
                    await self._speaker.speak(binding.runtime_session_id, text)
                except Exception:
                    continue
        except asyncio.CancelledError:
            raise
