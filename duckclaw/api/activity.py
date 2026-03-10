"""Agent Activity Manager — state machine and registry for worker availability.

Maintains a per-worker status (IDLE, BUSY, WAITING, ERROR) that acts as the
Single Source of Truth for Angular, WhatsApp/n8n and any other consumer.

The default backend is in-memory; set ``DUCKCLAW_REDIS_URL`` to switch to Redis
for multi-process deployments.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Optional, Protocol

logger = logging.getLogger(__name__)

# Heartbeat timeout: if no ping for this many seconds the task is zombie.
HEARTBEAT_TIMEOUT_S = int(os.environ.get("DUCKCLAW_HEARTBEAT_TIMEOUT", "30"))
# Zombie check interval
ZOMBIE_CHECK_INTERVAL_S = int(os.environ.get("DUCKCLAW_ZOMBIE_CHECK_INTERVAL", "10"))


class AgentStatus(str, Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    WAITING = "WAITING"
    ERROR = "ERROR"


@dataclass
class AgentState:
    worker_id: str
    status: AgentStatus = AgentStatus.IDLE
    task_id: Optional[str] = None
    task_description: Optional[str] = None
    since: Optional[str] = None
    last_heartbeat: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "task": self.task_description,
            "task_id": self.task_id,
            "since": self.since,
        }


class AgentRegistryBackend(Protocol):
    """Abstract backend — implement for Redis or any other store."""

    def get_state(self, worker_id: str) -> AgentState: ...
    def set_state(self, state: AgentState) -> None: ...
    def get_all(self) -> dict[str, AgentState]: ...
    def delete(self, worker_id: str) -> None: ...


class InMemoryBackend:
    """Thread-safe in-memory backend (single-process deployments)."""

    def __init__(self) -> None:
        self._store: dict[str, AgentState] = {}

    def get_state(self, worker_id: str) -> AgentState:
        return self._store.get(worker_id, AgentState(worker_id=worker_id))

    def set_state(self, state: AgentState) -> None:
        self._store[state.worker_id] = state

    def get_all(self) -> dict[str, AgentState]:
        return dict(self._store)

    def delete(self, worker_id: str) -> None:
        self._store.pop(worker_id, None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ActivityManager:
    """Central coordinator for agent state transitions and event broadcasting."""

    def __init__(self, backend: Optional[AgentRegistryBackend] = None) -> None:
        self._backend: AgentRegistryBackend = backend or InMemoryBackend()
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._zombie_task: Optional[asyncio.Task[None]] = None

    # -- State transitions ---------------------------------------------------

    def mark_busy(
        self,
        worker_id: str,
        task_description: str = "",
        task_id: Optional[str] = None,
    ) -> AgentState:
        """Transition worker to BUSY. Returns the new state."""
        state = AgentState(
            worker_id=worker_id,
            status=AgentStatus.BUSY,
            task_id=task_id or str(uuid.uuid4()),
            task_description=task_description or None,
            since=_now_iso(),
            last_heartbeat=time.monotonic(),
        )
        self._backend.set_state(state)
        self._broadcast(state)
        return state

    def mark_idle(self, worker_id: str) -> AgentState:
        """Transition worker to IDLE after task completion."""
        state = AgentState(
            worker_id=worker_id,
            status=AgentStatus.IDLE,
            since=_now_iso(),
        )
        self._backend.set_state(state)
        self._broadcast(state)
        return state

    def mark_waiting(self, worker_id: str, task_id: Optional[str] = None) -> AgentState:
        """Transition worker to WAITING (HITL approval pending)."""
        prev = self._backend.get_state(worker_id)
        state = AgentState(
            worker_id=worker_id,
            status=AgentStatus.WAITING,
            task_id=task_id or prev.task_id,
            task_description=prev.task_description,
            since=_now_iso(),
            last_heartbeat=time.monotonic(),
        )
        self._backend.set_state(state)
        self._broadcast(state)
        return state

    def mark_error(self, worker_id: str, detail: str = "") -> AgentState:
        """Transition worker to ERROR."""
        state = AgentState(
            worker_id=worker_id,
            status=AgentStatus.ERROR,
            task_description=detail or None,
            since=_now_iso(),
        )
        self._backend.set_state(state)
        self._broadcast(state)
        return state

    def heartbeat(self, worker_id: str) -> bool:
        """Record a heartbeat ping. Returns False if worker is not BUSY/WAITING."""
        state = self._backend.get_state(worker_id)
        if state.status not in (AgentStatus.BUSY, AgentStatus.WAITING):
            return False
        state.last_heartbeat = time.monotonic()
        self._backend.set_state(state)
        return True

    # -- Queries -------------------------------------------------------------

    def get_status(self, worker_id: str) -> AgentState:
        return self._backend.get_state(worker_id)

    def get_all_statuses(self) -> dict[str, dict[str, Any]]:
        return {wid: s.to_dict() for wid, s in self._backend.get_all().items()}

    def is_busy(self, worker_id: str) -> bool:
        return self._backend.get_state(worker_id).status == AgentStatus.BUSY

    # -- SSE broadcast -------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _broadcast(self, state: AgentState) -> None:
        event = {"worker_id": state.worker_id, **state.to_dict()}
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    async def activity_stream(self) -> AsyncGenerator[str, None]:
        """Yield SSE events when any agent changes state."""
        import json
        q = self.subscribe()
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(q)

    # -- Zombie detection ----------------------------------------------------

    def check_zombies(self) -> list[str]:
        """Find workers stuck in BUSY/WAITING past heartbeat timeout. Returns list of released worker_ids."""
        now = time.monotonic()
        released: list[str] = []
        for wid, state in self._backend.get_all().items():
            if state.status in (AgentStatus.BUSY, AgentStatus.WAITING):
                hb = state.last_heartbeat or 0.0
                if now - hb > HEARTBEAT_TIMEOUT_S:
                    logger.warning(
                        "Zombie detected: worker=%s was %s for %.0fs, releasing to ERROR",
                        wid, state.status.value, now - hb,
                    )
                    self.mark_error(wid, detail="Heartbeat timeout — tarea zombie detectada")
                    released.append(wid)
        return released

    async def start_zombie_watcher(self) -> None:
        """Background coroutine that periodically checks for zombie tasks."""
        while True:
            await asyncio.sleep(ZOMBIE_CHECK_INTERVAL_S)
            try:
                self.check_zombies()
            except Exception:
                logger.debug("Error in zombie watcher", exc_info=True)

    def ensure_zombie_watcher(self) -> None:
        """Start the zombie watcher if not already running."""
        if self._zombie_task is None or self._zombie_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._zombie_task = loop.create_task(self.start_zombie_watcher())
            except RuntimeError:
                pass


# -- Singleton ---------------------------------------------------------------

_manager: Optional[ActivityManager] = None


def get_activity_manager() -> ActivityManager:
    """Return the process-global ActivityManager singleton."""
    global _manager
    if _manager is None:
        _manager = ActivityManager()
    return _manager
