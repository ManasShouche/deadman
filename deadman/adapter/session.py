"""Observe-only ingestion of persisted Codex CLI session events."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from deadman.adapter.jsonl import AdapterParseResult
from deadman.domain import (
    EventSourceCursor,
    SessionEvent,
    SessionEventKind,
    SessionMode,
    SessionOwnership,
    SessionRecord,
    WatchSnapshot,
)
from deadman.store import EvidenceStore


@dataclass(frozen=True)
class SessionCandidate:
    """One persisted interactive Codex session eligible for explicit pairing."""

    session_id: str
    path: Path
    cwd: Path
    source: str
    cli_version: str | None
    started_at: float
    modified_at: float


def default_codex_home() -> Path:
    """Resolve the local Codex home without assuming the default path in tests."""

    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def discover_cli_sessions(
    workspace: Path,
    *,
    codex_home: Path | None = None,
) -> tuple[SessionCandidate, ...]:
    """Find persisted interactive CLI sessions for exactly one workspace."""

    sessions_root = (codex_home or default_codex_home()) / "sessions"
    if not sessions_root.exists():
        return ()

    expected_cwd = workspace.resolve()
    newest_by_id: dict[str, SessionCandidate] = {}
    for path in sessions_root.glob("**/*.jsonl"):
        candidate = _read_candidate(path)
        if candidate is None or candidate.source != "cli":
            continue
        if candidate.cwd.resolve() != expected_cwd:
            continue
        previous = newest_by_id.get(candidate.session_id)
        if previous is None or candidate.modified_at > previous.modified_at:
            newest_by_id[candidate.session_id] = candidate

    return tuple(
        sorted(newest_by_id.values(), key=lambda candidate: candidate.modified_at, reverse=True)
    )


def select_cli_session(
    session_id: str,
    workspace: Path,
    *,
    codex_home: Path | None = None,
) -> SessionCandidate:
    """Resolve an explicitly paired session and enforce repository matching."""

    candidates = discover_cli_sessions(workspace, codex_home=codex_home)
    for candidate in candidates:
        if candidate.session_id == session_id:
            return candidate
    raise ValueError(f"no interactive Codex session {session_id!r} matches {workspace.resolve()}")


def ingest_session(candidate: SessionCandidate, store: EvidenceStore) -> WatchSnapshot:
    """Ingest complete appended lines and return an observe-only status snapshot."""

    stat = candidate.path.stat()
    now = time.time()
    store.upsert_session(
        SessionRecord(
            session_id=candidate.session_id,
            external_session_id=candidate.session_id,
            mode=SessionMode.ATTACH,
            source=candidate.source,
            cwd=str(candidate.cwd),
            ownership=SessionOwnership.UNPROVEN,
            status="observing",
            cli_version=candidate.cli_version,
            started_at=candidate.started_at,
            last_seen_at=now,
        )
    )

    previous = store.latest_event_source(candidate.path)
    generation = 0 if previous is None else previous.generation
    offset = 0 if previous is None else previous.byte_offset
    if previous is not None and (previous.inode != stat.st_ino or stat.st_size < offset):
        generation += 1
        offset = 0

    source_id = _source_id(candidate.path, stat.st_ino, generation)
    events, next_offset = _read_complete_events(
        candidate,
        source_id=source_id,
        offset=offset,
        fallback_timestamp=stat.st_mtime,
    )
    store.upsert_event_source(
        EventSourceCursor(
            source_id=source_id,
            session_id=candidate.session_id,
            path=str(candidate.path),
            inode=stat.st_ino,
            generation=generation,
            byte_offset=offset,
            updated_at=now,
        )
    )
    inserted = store.add_session_events(events)
    store.upsert_event_source(
        EventSourceCursor(
            source_id=source_id,
            session_id=candidate.session_id,
            path=str(candidate.path),
            inode=stat.st_ino,
            generation=generation,
            byte_offset=next_offset,
            updated_at=now,
        )
    )
    return _snapshot(candidate, store, inserted)


def persist_managed_events(
    parsed: AdapterParseResult,
    *,
    workspace: Path,
    store: EvidenceStore,
) -> str:
    """Register one managed JSONL capture in the canonical session store."""

    now = time.time()
    external_id = parsed.capabilities.persisted_session_id
    session_id = external_id or f"managed:{uuid.uuid4()}"
    source_id = f"managed-source:{uuid.uuid4()}"
    store.upsert_session(
        SessionRecord(
            session_id=session_id,
            external_session_id=external_id,
            mode=SessionMode.MANAGED,
            source="codex_exec",
            cwd=str(workspace.resolve()),
            ownership=SessionOwnership.MANAGED,
            status="captured",
            started_at=now,
            last_seen_at=now,
        )
    )
    store.upsert_event_source(
        EventSourceCursor(
            source_id=source_id,
            session_id=session_id,
            path=f"managed://{source_id}",
            inode=0,
            byte_offset=len(parsed.raw_events),
            updated_at=now,
        )
    )
    events = tuple(
        SessionEvent(
            evidence_id=_evidence_id(source_id, raw.line_number, raw.raw_line),
            session_id=session_id,
            source_id=source_id,
            source_offset=raw.line_number,
            observed_at=now + raw.line_number / 1_000_000,
            raw_line=raw.raw_line,
            raw_event_type=raw.event_type,
            kind=_managed_event_kind(raw.event_type, raw.parsed),
            payload=raw.parsed,
            parse_error=raw.parse_error,
        )
        for raw in parsed.raw_events
    )
    store.add_session_events(events)
    return session_id


def _read_candidate(path: Path) -> SessionCandidate | None:
    try:
        stat = path.stat()
        with path.open(encoding="utf-8", errors="replace") as handle:
            for _ in range(64):
                line = handle.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("type") != "session_meta":
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    return None
                session_id = payload.get("id")
                cwd = payload.get("cwd")
                source = payload.get("source")
                if (
                    not isinstance(session_id, str)
                    or not isinstance(cwd, str)
                    or not isinstance(source, str)
                ):
                    return None
                timestamp = _event_timestamp(event, stat.st_mtime)
                cli_version = payload.get("cli_version")
                return SessionCandidate(
                    session_id=session_id,
                    path=path.resolve(),
                    cwd=Path(cwd),
                    source=source,
                    cli_version=cli_version if isinstance(cli_version, str) else None,
                    started_at=timestamp,
                    modified_at=stat.st_mtime,
                )
    except OSError:
        return None
    return None


def _read_complete_events(
    candidate: SessionCandidate,
    *,
    source_id: str,
    offset: int,
    fallback_timestamp: float,
) -> tuple[tuple[SessionEvent, ...], int]:
    with candidate.path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()

    events: list[SessionEvent] = []
    consumed = 0
    while True:
        newline = data.find(b"\n", consumed)
        if newline < 0:
            break
        raw_bytes = data[consumed:newline]
        line_offset = offset + consumed
        raw_line = raw_bytes.rstrip(b"\r").decode("utf-8", errors="replace")
        events.append(
            _normalize_line(
                raw_line,
                session_id=candidate.session_id,
                source_id=source_id,
                source_offset=line_offset,
                fallback_timestamp=fallback_timestamp,
            )
        )
        consumed = newline + 1
    return tuple(events), offset + consumed


def _normalize_line(
    raw_line: str,
    *,
    session_id: str,
    source_id: str,
    source_offset: int,
    fallback_timestamp: float,
) -> SessionEvent:
    evidence_id = _evidence_id(source_id, source_offset, raw_line)
    try:
        parsed = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        return SessionEvent(
            evidence_id=evidence_id,
            session_id=session_id,
            source_id=source_id,
            source_offset=source_offset,
            observed_at=fallback_timestamp,
            raw_line=raw_line,
            raw_event_type="malformed_json",
            kind=SessionEventKind.MALFORMED,
            parse_error=str(exc),
        )
    if not isinstance(parsed, dict):
        return SessionEvent(
            evidence_id=evidence_id,
            session_id=session_id,
            source_id=source_id,
            source_offset=source_offset,
            observed_at=fallback_timestamp,
            raw_line=raw_line,
            raw_event_type="non_object_json",
            kind=SessionEventKind.UNKNOWN,
            payload={"value": parsed},
        )

    outer_type = str(parsed.get("type", "unknown"))
    payload = parsed.get("payload")
    inner_type = payload.get("type") if isinstance(payload, dict) else None
    raw_event_type = outer_type if not isinstance(inner_type, str) else f"{outer_type}:{inner_type}"
    return SessionEvent(
        evidence_id=evidence_id,
        session_id=session_id,
        source_id=source_id,
        source_offset=source_offset,
        observed_at=_event_timestamp(parsed, fallback_timestamp),
        raw_line=raw_line,
        raw_event_type=raw_event_type,
        kind=_event_kind(outer_type, inner_type),
        payload=parsed,
    )


def _event_kind(outer_type: str, inner_type: object) -> SessionEventKind:
    if outer_type == "session_meta":
        return SessionEventKind.SESSION_STARTED
    if outer_type == "turn_context":
        return SessionEventKind.TURN_CONTEXT
    if outer_type == "event_msg":
        return {
            "task_started": SessionEventKind.TURN_STARTED,
            "task_complete": SessionEventKind.TURN_COMPLETED,
            "token_count": SessionEventKind.USAGE_UPDATED,
            "context_compacted": SessionEventKind.COMPACTION,
            "user_message": SessionEventKind.MESSAGE,
            "agent_message": SessionEventKind.MESSAGE,
        }.get(str(inner_type), SessionEventKind.UNKNOWN)
    if outer_type == "response_item":
        return {
            "custom_tool_call": SessionEventKind.TOOL_CALL_STARTED,
            "custom_tool_call_output": SessionEventKind.TOOL_CALL_COMPLETED,
            "message": SessionEventKind.MESSAGE,
        }.get(str(inner_type), SessionEventKind.UNKNOWN)
    return SessionEventKind.UNKNOWN


def _managed_event_kind(
    event_type: str,
    payload: dict[str, Any] | None,
) -> SessionEventKind:
    if event_type == "malformed_json":
        return SessionEventKind.MALFORMED
    if event_type == "thread.started":
        return SessionEventKind.SESSION_STARTED
    if event_type == "turn.started":
        return SessionEventKind.TURN_STARTED
    if event_type == "turn.completed":
        return SessionEventKind.TURN_COMPLETED
    item = payload.get("item") if payload is not None else None
    item_type = item.get("type") if isinstance(item, dict) else None
    if event_type == "item.started" and item_type in {"command_execution", "tool_call"}:
        return SessionEventKind.TOOL_CALL_STARTED
    if event_type == "item.completed" and item_type in {"command_execution", "tool_call"}:
        return SessionEventKind.TOOL_CALL_COMPLETED
    if event_type == "item.completed" and item_type == "agent_message":
        return SessionEventKind.MESSAGE
    return SessionEventKind.UNKNOWN


def _event_timestamp(event: dict[str, Any], fallback: float) -> float:
    value = event.get("timestamp")
    if not isinstance(value, str):
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return fallback


def _snapshot(
    candidate: SessionCandidate,
    store: EvidenceStore,
    inserted: int,
) -> WatchSnapshot:
    latest = store.latest_session_event(candidate.session_id)
    latest_turn = store.latest_session_event_of_types(
        candidate.session_id,
        (
            SessionEventKind.TURN_STARTED.value,
            SessionEventKind.TURN_COMPLETED.value,
        ),
    )
    kinds = set(store.session_event_kinds(candidate.session_id))
    capabilities = []
    if SessionEventKind.USAGE_UPDATED.value in kinds:
        capabilities.append("usage")
    if {
        SessionEventKind.TOOL_CALL_STARTED.value,
        SessionEventKind.TOOL_CALL_COMPLETED.value,
    } & kinds:
        capabilities.append("tool_calls")
    if SessionEventKind.COMPACTION.value in kinds:
        capabilities.append("compaction")
    if SessionEventKind.TURN_COMPLETED.value in kinds:
        capabilities.append("completion")

    latest_kind = (
        SessionEventKind(str(latest["normalized_type"])) if latest is not None else None
    )
    latest_turn_kind = (
        SessionEventKind(str(latest_turn["normalized_type"]))
        if latest_turn is not None
        else None
    )
    if latest_turn_kind is SessionEventKind.TURN_STARTED:
        turn_state = "active"
    elif latest_turn_kind is SessionEventKind.TURN_COMPLETED:
        turn_state = "idle"
    else:
        turn_state = "observing"
    return WatchSnapshot(
        session_id=candidate.session_id,
        source=candidate.source,
        cwd=str(candidate.cwd),
        event_count=store.session_event_count(candidate.session_id),
        new_event_count=inserted,
        last_event_kind=latest_kind,
        last_event_at=float(latest["observed_at"]) if latest is not None else None,
        turn_state=turn_state,
        capabilities=tuple(capabilities),
        active_signals=store.active_signal_kinds(candidate.session_id),
    )


def _source_id(path: Path, inode: int, generation: int) -> str:
    digest = hashlib.sha256(f"{path}:{inode}:{generation}".encode()).hexdigest()[:20]
    return f"source:{digest}"


def _evidence_id(source_id: str, offset: int, raw_line: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{offset}:{raw_line}".encode()).hexdigest()[:20]
    return f"event:{digest}"
