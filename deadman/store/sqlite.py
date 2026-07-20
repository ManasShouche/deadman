"""SQLite-backed evidence store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from deadman.domain import (
    ActionResult,
    CapabilityReport,
    Diagnosis,
    EventSourceCursor,
    Incident,
    NormalizedEvent,
    PolicyDecision,
    ProcessObservation,
    RawAdapterEvent,
    SessionEvent,
    SessionRecord,
    Signal,
    StateTransition,
    VerificationResult,
)


class EvidenceStore:
    """Small repository for D1 evidence records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add_raw_events(self, events: Iterable[RawAdapterEvent]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert or replace into raw_events
                (id, line_number, event_type, raw_line, parse_error, payload_json)
                values (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event.evidence_id,
                        event.line_number,
                        event.event_type,
                        event.raw_line,
                        event.parse_error,
                        _json_dumps(event.parsed),
                    )
                    for event in events
                ],
            )

    def add_normalized_events(self, events: Iterable[NormalizedEvent]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert or replace into normalized_events
                (id, raw_event_id, event_type, payload_json)
                values (?, ?, ?, ?)
                """,
                [
                    (
                        event.evidence_id,
                        event.raw_evidence_id,
                        event.event_type,
                        _model_json(event),
                    )
                    for event in events
                ],
            )

    def add_capability_report(self, report: CapabilityReport) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "insert into capability_reports (payload_json) values (?)",
                (_model_json(report),),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a capability report id")
            return int(cursor.lastrowid)

    def upsert_session(self, session: SessionRecord) -> None:
        """Create or refresh a session without changing its ownership boundary."""

        with self._connect() as connection:
            connection.execute(
                """
                insert into sessions
                (id, external_session_id, mode, source, cwd, ownership, status,
                 cli_version, started_at, last_seen_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    external_session_id = excluded.external_session_id,
                    source = excluded.source,
                    cwd = excluded.cwd,
                    status = excluded.status,
                    cli_version = coalesce(excluded.cli_version, sessions.cli_version),
                    last_seen_at = max(excluded.last_seen_at, sessions.last_seen_at)
                """,
                (
                    session.session_id,
                    session.external_session_id,
                    session.mode.value,
                    session.source,
                    session.cwd,
                    session.ownership.value,
                    session.status,
                    session.cli_version,
                    session.started_at,
                    session.last_seen_at,
                ),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return one stored session as a plain mapping."""

        with self._connect() as connection:
            row = connection.execute(
                "select * from sessions where id = ?",
                (session_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def add_session_events(self, events: Iterable[SessionEvent]) -> int:
        """Persist session events idempotently and return the inserted count."""

        event_list = list(events)
        if not event_list:
            return 0
        with self._connect() as connection:
            before = connection.total_changes
            connection.executemany(
                """
                insert or ignore into events
                (id, session_id, source_id, source_offset, observed_at, raw_line,
                 raw_event_type, normalized_type, payload_json, parse_error)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event.evidence_id,
                        event.session_id,
                        event.source_id,
                        event.source_offset,
                        event.observed_at,
                        event.raw_line,
                        event.raw_event_type,
                        event.kind.value,
                        _json_dumps(event.payload),
                        event.parse_error,
                    )
                    for event in event_list
                ],
            )
            return connection.total_changes - before

    def latest_event_source(self, path: Path) -> EventSourceCursor | None:
        """Return the newest cursor generation for one persisted source path."""

        with self._connect() as connection:
            row = connection.execute(
                """
                select * from event_sources where path = ?
                order by generation desc limit 1
                """,
                (str(path),),
            ).fetchone()
        if row is None:
            return None
        return EventSourceCursor(
            source_id=row["id"],
            session_id=row["session_id"],
            path=row["path"],
            inode=row["inode"],
            generation=row["generation"],
            byte_offset=row["byte_offset"],
            updated_at=row["updated_at"],
        )

    def upsert_event_source(self, cursor: EventSourceCursor) -> None:
        """Persist an append-only source cursor after complete lines are stored."""

        with self._connect() as connection:
            connection.execute(
                """
                insert into event_sources
                (id, session_id, path, inode, generation, byte_offset, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    byte_offset = excluded.byte_offset,
                    updated_at = excluded.updated_at
                """,
                (
                    cursor.source_id,
                    cursor.session_id,
                    cursor.path,
                    cursor.inode,
                    cursor.generation,
                    cursor.byte_offset,
                    cursor.updated_at,
                ),
            )

    def session_event_count(self, session_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "select count(*) as count from events where session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["count"])

    def latest_session_event(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select * from events where session_id = ?
                order by observed_at desc, source_offset desc limit 1
                """,
                (session_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def latest_session_event_of_types(
        self,
        session_id: str,
        event_types: tuple[str, ...],
    ) -> dict[str, Any] | None:
        if not event_types:
            return None
        placeholders = ",".join("?" for _ in event_types)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                select * from events where session_id = ?
                and normalized_type in ({placeholders})
                order by observed_at desc, source_offset desc limit 1
                """,
                (session_id, *event_types),
            ).fetchone()
        return None if row is None else dict(row)

    def session_event_kinds(self, session_id: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select distinct normalized_type from events
                where session_id = ? order by normalized_type
                """,
                (session_id,),
            ).fetchall()
        return tuple(str(row["normalized_type"]) for row in rows)

    def active_signal_kinds(self, session_id: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "select distinct kind from signals where session_id = ? order by kind",
                (session_id,),
            ).fetchall()
        return tuple(str(row["kind"]) for row in rows)

    def add_process_observations(
        self,
        observations: Iterable[ProcessObservation],
        *,
        session_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert or replace into process_observations
                (id, root_pid, pid, payload_json, session_id)
                values (?, ?, ?, ?, ?)
                """,
                [
                    (
                        observation.evidence_id,
                        observation.root_pid,
                        observation.pid,
                        _model_json(observation),
                        session_id,
                    )
                    for observation in observations
                ],
            )

    def add_signals(
        self,
        signals: Iterable[Signal],
        *,
        session_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert or replace into signals
                (fingerprint, kind, payload_json, session_id)
                values (?, ?, ?, ?)
                """,
                [
                    (signal.fingerprint, signal.kind.value, _model_json(signal), session_id)
                    for signal in signals
                ],
            )

    def add_incident(self, incident: Incident, *, session_id: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert or replace into incidents
                (id, state, payload_json, session_id)
                values (?, ?, ?, ?)
                """,
                (incident.incident_id, incident.state.value, _model_json(incident), session_id),
            )

    def add_transitions(self, incident_id: str, transitions: Iterable[StateTransition]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert into transitions
                (incident_id, from_state, to_state, payload_json)
                values (?, ?, ?, ?)
                """,
                [
                    (
                        incident_id,
                        transition.from_state.value,
                        transition.to_state.value,
                        _model_json(transition),
                    )
                    for transition in transitions
                ],
            )

    def add_diagnosis(self, incident_id: str, diagnosis: Diagnosis) -> None:
        self._add_incident_payload("diagnoses", incident_id, _model_json(diagnosis))

    def add_policy_decision(self, incident_id: str, decision: PolicyDecision) -> None:
        self._add_incident_payload("policy_decisions", incident_id, _model_json(decision))

    def add_action_result(self, incident_id: str, action_result: ActionResult) -> None:
        self._add_incident_payload("action_results", incident_id, _model_json(action_result))
        self._add_incident_payload("actions", incident_id, _model_json(action_result))

    def add_verification_result(
        self,
        incident_id: str,
        verification_result: VerificationResult,
    ) -> None:
        self._add_incident_payload(
            "verification_results",
            incident_id,
            _model_json(verification_result),
        )
        self._add_incident_payload(
            "verifications",
            incident_id,
            _model_json(verification_result),
        )

    def add_canonical_transitions(
        self,
        incident: Incident,
        *,
        policy: PolicyDecision | None,
        action_result: ActionResult | None,
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert into incident_transitions
                (incident_id, from_state, to_state, trigger, actor, evidence_json,
                 policy_json, action_json, occurred_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        incident.incident_id,
                        transition.from_state.value,
                        transition.to_state.value,
                        transition.reason,
                        transition.actor,
                        json.dumps(transition.evidence_ids),
                        _model_json(policy) if policy is not None else None,
                        _model_json(action_result) if action_result is not None else None,
                        transition.timestamp,
                    )
                    for transition in incident.transitions
                ],
            )

    def add_report(self, incident_id: str, report: str) -> None:
        payload = json.dumps({"report": report}, sort_keys=True, separators=(",", ":"))
        self._add_incident_payload("reports", incident_id, payload)

    def list_payloads(self, table: str) -> list[dict[str, Any]]:
        if table not in _PAYLOAD_TABLES:
            raise ValueError(f"unsupported payload table: {table}")

        with self._connect() as connection:
            rows = connection.execute(f"select payload_json from {table} order by rowid").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def count(self, table: str) -> int:
        if table not in _ALL_TABLES:
            raise ValueError(f"unsupported table: {table}")

        with self._connect() as connection:
            row = connection.execute(f"select count(*) as count from {table}").fetchone()
        return int(row["count"])

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                create table if not exists raw_events (
                    id text primary key,
                    line_number integer not null,
                    event_type text not null,
                    raw_line text not null,
                    parse_error text,
                    payload_json text
                );

                create table if not exists normalized_events (
                    id text primary key,
                    raw_event_id text not null,
                    event_type text not null,
                    payload_json text not null
                );

                create table if not exists capability_reports (
                    id integer primary key autoincrement,
                    created_at text not null default current_timestamp,
                    payload_json text not null
                );

                create table if not exists process_observations (
                    id text primary key,
                    root_pid integer not null,
                    pid integer not null,
                    payload_json text not null
                );

                create table if not exists signals (
                    fingerprint text primary key,
                    kind text not null,
                    payload_json text not null
                );

                create table if not exists incidents (
                    id text primary key,
                    state text not null,
                    payload_json text not null
                );

                create table if not exists transitions (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    from_state text not null,
                    to_state text not null,
                    payload_json text not null
                );

                create table if not exists diagnoses (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    payload_json text not null
                );

                create table if not exists action_results (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    payload_json text not null
                );

                create table if not exists verification_results (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    payload_json text not null
                );

                create table if not exists reports (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    payload_json text not null
                );

                create table if not exists schema_migrations (
                    version integer primary key,
                    applied_at text not null default current_timestamp
                );

                create table if not exists sessions (
                    id text primary key,
                    external_session_id text,
                    mode text not null,
                    source text not null,
                    cwd text not null,
                    ownership text not null,
                    status text not null,
                    cli_version text,
                    started_at real not null,
                    last_seen_at real not null
                );

                create table if not exists event_sources (
                    id text primary key,
                    session_id text not null references sessions(id),
                    path text not null,
                    inode integer not null,
                    generation integer not null,
                    byte_offset integer not null,
                    updated_at real not null,
                    unique(path, generation)
                );

                create table if not exists events (
                    id text primary key,
                    session_id text not null references sessions(id),
                    source_id text not null references event_sources(id),
                    source_offset integer not null,
                    observed_at real not null,
                    raw_line text not null,
                    raw_event_type text not null,
                    normalized_type text not null,
                    payload_json text,
                    parse_error text,
                    unique(source_id, source_offset)
                );

                create table if not exists workspace_snapshots (
                    id text primary key,
                    session_id text not null references sessions(id),
                    observed_at real not null,
                    fingerprint text not null,
                    payload_json text not null
                );

                create table if not exists incident_transitions (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    from_state text not null,
                    to_state text not null,
                    trigger text not null,
                    actor text not null,
                    evidence_json text not null,
                    policy_json text,
                    action_json text,
                    occurred_at real not null
                );

                create table if not exists policy_decisions (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    payload_json text not null
                );

                create table if not exists actions (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    payload_json text not null
                );

                create table if not exists verifications (
                    id integer primary key autoincrement,
                    incident_id text not null,
                    payload_json text not null
                );
                """
            )
            _ensure_column(connection, "process_observations", "session_id", "text")
            _ensure_column(connection, "signals", "session_id", "text")
            _ensure_column(connection, "incidents", "session_id", "text")
            _migrate_legacy_evidence(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        return connection

    def _add_incident_payload(self, table: str, incident_id: str, payload_json: str) -> None:
        if table not in _INCIDENT_PAYLOAD_TABLES:
            raise ValueError(f"unsupported incident payload table: {table}")
        with self._connect() as connection:
            connection.execute(
                f"insert into {table} (incident_id, payload_json) values (?, ?)",
                (incident_id, payload_json),
            )


_PAYLOAD_TABLES = frozenset(
    {
        "normalized_events",
        "capability_reports",
        "process_observations",
        "signals",
        "incidents",
        "transitions",
        "diagnoses",
        "action_results",
        "verification_results",
        "reports",
        "policy_decisions",
        "actions",
        "verifications",
    }
)
_ALL_TABLES = _PAYLOAD_TABLES | {
    "raw_events",
    "sessions",
    "event_sources",
    "events",
    "workspace_snapshots",
    "incident_transitions",
    "schema_migrations",
}
_INCIDENT_PAYLOAD_TABLES = frozenset(
    {
        "diagnoses",
        "policy_decisions",
        "action_results",
        "actions",
        "verification_results",
        "verifications",
        "reports",
    }
)


def _model_json(model: BaseModel) -> str:
    return model.model_dump_json()


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {row["name"] for row in connection.execute(f"pragma table_info({table})")}
    if column not in columns:
        connection.execute(f"alter table {table} add column {column} {definition}")


def _migrate_legacy_evidence(connection: sqlite3.Connection) -> None:
    if connection.execute(
        "select 1 from schema_migrations where version = 2"
    ).fetchone() is not None:
        return

    legacy_session_id = "legacy-unscoped"
    connection.execute(
        """
        insert or ignore into sessions
        (id, external_session_id, mode, source, cwd, ownership, status,
         cli_version, started_at, last_seen_at)
        values (?, null, 'legacy', 'legacy', '', 'unproven', 'migrated', null, 0, 0)
        """,
        (legacy_session_id,),
    )
    connection.execute(
        """
        insert or ignore into event_sources
        (id, session_id, path, inode, generation, byte_offset, updated_at)
        values ('legacy-source', ?, 'legacy://raw_events', 0, 0, 0, 0)
        """,
        (legacy_session_id,),
    )
    rows = connection.execute(
        """
        select id, line_number, event_type, raw_line, parse_error, payload_json
        from raw_events order by line_number
        """
    ).fetchall()
    connection.executemany(
        """
        insert or ignore into events
        (id, session_id, source_id, source_offset, observed_at, raw_line,
         raw_event_type, normalized_type, payload_json, parse_error)
        values (?, ?, 'legacy-source', ?, 0, ?, ?, ?, ?, ?)
        """,
        [
            (
                f"legacy:{row['id']}",
                legacy_session_id,
                row["line_number"],
                row["raw_line"],
                row["event_type"],
                "MALFORMED" if row["parse_error"] else "UNKNOWN",
                row["payload_json"],
                row["parse_error"],
            )
            for row in rows
        ],
    )
    connection.execute("insert into schema_migrations(version) values (2)")
