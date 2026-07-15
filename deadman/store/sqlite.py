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
    Incident,
    NormalizedEvent,
    ProcessObservation,
    RawAdapterEvent,
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

    def add_process_observations(self, observations: Iterable[ProcessObservation]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert or replace into process_observations
                (id, root_pid, pid, payload_json)
                values (?, ?, ?, ?)
                """,
                [
                    (
                        observation.evidence_id,
                        observation.root_pid,
                        observation.pid,
                        _model_json(observation),
                    )
                    for observation in observations
                ],
            )

    def add_signals(self, signals: Iterable[Signal]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                insert or replace into signals
                (fingerprint, kind, payload_json)
                values (?, ?, ?)
                """,
                [
                    (signal.fingerprint, signal.kind.value, _model_json(signal))
                    for signal in signals
                ],
            )

    def add_incident(self, incident: Incident) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert or replace into incidents
                (id, state, payload_json)
                values (?, ?, ?)
                """,
                (incident.incident_id, incident.state.value, _model_json(incident)),
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

    def add_action_result(self, incident_id: str, action_result: ActionResult) -> None:
        self._add_incident_payload("action_results", incident_id, _model_json(action_result))

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
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
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
    }
)
_ALL_TABLES = _PAYLOAD_TABLES | {"raw_events"}
_INCIDENT_PAYLOAD_TABLES = frozenset(
    {"diagnoses", "action_results", "verification_results", "reports"}
)


def _model_json(model: BaseModel) -> str:
    return model.model_dump_json()


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
