from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ProbeBucket:
    second: int
    success_count: int = 0
    error_count: int = 0


@dataclass(slots=True)
class _ProbeState:
    last_event_id: str | None = None
    buckets: deque[_ProbeBucket] = field(default_factory=deque)
    recent_events: deque[dict[str, Any]] = field(default_factory=deque)
    latest_event: dict[str, Any] | None = None


class ProbeService:
    def __init__(
        self,
        state_repo: TestStateRepository,
        *,
        declared_probe_names: list[str] | None = None,
        poll_interval_s: float = 1.0,
        window_s: int = 60,
        max_events_per_probe_per_poll: int = 300,
        max_recent_events_per_probe: int = 100,
    ) -> None:
        self._state_repo = state_repo
        self._declared_probe_names = sorted(set(declared_probe_names or []))
        self._poll_interval_s = poll_interval_s
        self._window_s = max(1, window_s)
        self._max_events_per_probe_per_poll = max(1, max_events_per_probe_per_poll)
        self._max_recent_events_per_probe = max(1, max_recent_events_per_probe)

        self._probes: dict[str, _ProbeState] = {}
        self._probes_with_backlog: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="probe-poller")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def refresh_now(self) -> None:
        await self._poll_once()

    async def reset_for_new_run(self) -> None:
        deleted_keys = await self._state_repo.clear_probe_data()
        async with self._lock:
            self._probes.clear()
            self._probes_with_backlog.clear()
        logger.info("probes reset for new run deleted_keys=%s", deleted_keys)

    async def get_probes(
        self,
        *,
        probe_name: str | None = None,
        count: int = 20,
        include_events: bool = True,
    ) -> dict[str, object]:
        capped_count = max(0, min(count, self._max_recent_events_per_probe))
        known_probe_names = await self._known_probe_names(probe_name=probe_name)
        async with self._lock:
            for known_probe_name in known_probe_names:
                self._state_for(known_probe_name)
            return self._build_snapshot_locked(
                probe_name=probe_name,
                count=capped_count,
                include_events=include_events,
            )

    async def get_probe_history(
        self,
        *,
        probe_name: str,
        count: int = 100,
    ) -> dict[str, object]:
        if not probe_name.strip():
            raise ValueError("probe_name must not be empty")
        snapshot = await self.get_probes(
            probe_name=probe_name,
            count=count,
            include_events=True,
        )
        probes = snapshot.get("probes")
        events: list[dict[str, Any]] = []
        last_event_id: str | None = None
        if isinstance(probes, list) and probes:
            probe_payload = probes[0]
            if isinstance(probe_payload, dict):
                raw_events = probe_payload.get("events")
                if isinstance(raw_events, list):
                    events = raw_events
                raw_last_event_id = probe_payload.get("last_event_id")
                if isinstance(raw_last_event_id, str):
                    last_event_id = raw_last_event_id
        return {
            "generated_at": snapshot["generated_at"],
            "probe_name": probe_name,
            "count": len(events),
            "last_event_id": last_event_id,
            "events": events,
        }

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001
                logger.exception("probe poll loop failed")
            await asyncio.sleep(self._poll_interval_s)

    async def _poll_once(self) -> None:
        probe_names = await self._known_probe_names(probe_name=None)
        if not probe_names:
            return

        async with self._lock:
            cursors = {
                current_probe_name: self._probes.get(current_probe_name, _ProbeState()).last_event_id
                for current_probe_name in probe_names
            }

        fetched: dict[str, list[dict[str, Any]]] = {}
        backlog_probes: set[str] = set()

        for current_probe_name in probe_names:
            events = await self._state_repo.read_probe_events_after(
                probe_name=current_probe_name,
                after_event_id=cursors.get(current_probe_name),
                count=self._max_events_per_probe_per_poll,
            )
            if events:
                fetched[current_probe_name] = events
            if len(events) >= self._max_events_per_probe_per_poll:
                backlog_probes.add(current_probe_name)

        if not fetched and not backlog_probes:
            return

        async with self._lock:
            for current_probe_name, events in fetched.items():
                state = self._state_for(current_probe_name)
                for event in events:
                    state.last_event_id = event["event_id"]
                    state.latest_event = event
                    state.recent_events.append(event)
                    while len(state.recent_events) > self._max_recent_events_per_probe:
                        state.recent_events.popleft()
                    self._apply_event(state, event)

            self._probes_with_backlog |= backlog_probes
            for current_probe_name in list(self._probes_with_backlog):
                if current_probe_name not in backlog_probes:
                    self._probes_with_backlog.discard(current_probe_name)

    async def _known_probe_names(self, *, probe_name: str | None) -> list[str]:
        if probe_name is not None:
            normalized = probe_name.strip()
            return [normalized] if normalized else []
        try:
            repo_probe_names = await self._state_repo.list_probes()
        except Exception:  # noqa: BLE001
            logger.exception("failed to list probes from state repo; returning cached snapshot")
            repo_probe_names = []
        return sorted(set(self._declared_probe_names) | set(repo_probe_names))

    def _state_for(self, probe_name: str) -> _ProbeState:
        state = self._probes.get(probe_name)
        if state is None:
            state = _ProbeState(recent_events=deque(maxlen=self._max_recent_events_per_probe))
            self._probes[probe_name] = state
        return state

    def _apply_event(self, state: _ProbeState, event: dict[str, Any]) -> None:
        payload = event.get("data")
        if not isinstance(payload, dict):
            payload = {}
        ts_ms = _extract_probe_ts_ms(event.get("event_id", "0-0"), payload)
        second = ts_ms // 1000
        bucket = self._ensure_bucket(state, second)
        if payload.get("status") is True:
            bucket.success_count += 1
        else:
            bucket.error_count += 1
        self._trim_buckets(state, current_second=second)

    def _ensure_bucket(self, state: _ProbeState, second: int) -> _ProbeBucket:
        if state.buckets and state.buckets[-1].second == second:
            return state.buckets[-1]
        bucket = _ProbeBucket(second=second)
        state.buckets.append(bucket)
        return bucket

    def _trim_buckets(self, state: _ProbeState, current_second: int) -> None:
        min_second = current_second - self._window_s + 1
        while state.buckets and state.buckets[0].second < min_second:
            state.buckets.popleft()

    def _build_snapshot_locked(
        self,
        *,
        probe_name: str | None,
        count: int,
        include_events: bool,
    ) -> dict[str, object]:
        now_ms = int(time.time() * 1000)
        probe_names = [probe_name] if probe_name else sorted(self._probes.keys())
        probes_payload: list[dict[str, object]] = []
        for current_probe_name in probe_names:
            state = self._probes.get(current_probe_name)
            if state is None:
                probes_payload.append(
                    {
                        "probe_name": current_probe_name,
                        "last_event_id": None,
                        "aggregate": self._empty_aggregate(),
                        "latest": None,
                        "events": [] if include_events else None,
                    }
                )
                continue

            latest_payload = _latest_payload(state.latest_event)
            events_payload: list[dict[str, Any]] | None = None
            if include_events:
                events_payload = [] if count == 0 else list(state.recent_events)[-count:]

            probes_payload.append(
                {
                    "probe_name": current_probe_name,
                    "last_event_id": state.last_event_id,
                    "aggregate": self._aggregate(state),
                    "latest": latest_payload,
                    "events": events_payload,
                }
            )

        return {
            "generated_at": int(now_ms / 1000),
            "lag": {
                "detected": bool(self._probes_with_backlog),
                "probes_with_backlog": sorted(self._probes_with_backlog),
            },
            "probes": probes_payload,
            "count": count,
            "include_events": include_events,
        }

    def _aggregate(self, state: _ProbeState) -> dict[str, object]:
        successes = sum(bucket.success_count for bucket in state.buckets)
        errors = sum(bucket.error_count for bucket in state.buckets)
        latest = _latest_payload(state.latest_event)
        return {
            "window_s": self._window_s,
            "successes": successes,
            "errors": errors,
            "last_ts_ms": latest["ts_ms"] if latest is not None else None,
            "last_status": latest["status"] if latest is not None else None,
            "last_value": latest["value"] if latest is not None else None,
        }

    def _empty_aggregate(self) -> dict[str, object]:
        return {
            "window_s": self._window_s,
            "successes": 0,
            "errors": 0,
            "last_ts_ms": None,
            "last_status": None,
            "last_value": None,
        }


def _extract_probe_ts_ms(event_id: str, payload: dict[str, Any]) -> int:
    raw_ts_ms = payload.get("ts_ms")
    if isinstance(raw_ts_ms, int):
        return raw_ts_ms
    if isinstance(raw_ts_ms, float):
        return int(raw_ts_ms)
    head = str(event_id).split("-", maxsplit=1)[0]
    try:
        return int(head)
    except ValueError:
        return int(time.time() * 1000)


def _latest_payload(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    payload = event.get("data")
    if not isinstance(payload, dict):
        return None
    return {
        "ts_ms": payload.get("ts_ms"),
        "status": payload.get("status"),
        "value": payload.get("value"),
        "time": payload.get("time"),
        "error_type": payload.get("error_type"),
        "error_message": payload.get("error_message"),
    }
