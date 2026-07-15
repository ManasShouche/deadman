"""Codex JSONL parsing and conservative capability detection."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict

from deadman.domain import CapabilityReport, NormalizedEvent, RawAdapterEvent


class AdapterParseResult(BaseModel):
    """Result of parsing a JSONL trace without dropping evidence."""

    model_config = ConfigDict(frozen=True)

    raw_events: tuple[RawAdapterEvent, ...]
    normalized_events: tuple[NormalizedEvent, ...]
    capabilities: CapabilityReport


def parse_jsonl_lines(lines: Iterable[str]) -> AdapterParseResult:
    """Parse Codex JSONL lines and retain malformed input as raw evidence."""

    raw_events: list[RawAdapterEvent] = []
    normalized_events: list[NormalizedEvent] = []

    for line_number, line in enumerate(lines, start=1):
        raw_line = line.rstrip("\n")
        evidence_id = f"evt_{line_number:06d}"
        try:
            parsed = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raw_events.append(
                RawAdapterEvent(
                    evidence_id=evidence_id,
                    line_number=line_number,
                    raw_line=raw_line,
                    event_type="malformed_json",
                    parse_error=str(exc),
                )
            )
            continue

        if not isinstance(parsed, dict):
            raw_events.append(
                RawAdapterEvent(
                    evidence_id=evidence_id,
                    line_number=line_number,
                    raw_line=raw_line,
                    event_type="non_object_json",
                    parsed={"value": parsed},
                )
            )
            continue

        event_type = str(parsed.get("type", "unknown"))
        raw_events.append(
            RawAdapterEvent(
                evidence_id=evidence_id,
                line_number=line_number,
                raw_line=raw_line,
                event_type=event_type,
                parsed=parsed,
            )
        )
        normalized_events.append(
            NormalizedEvent(
                evidence_id=f"norm_{line_number:06d}",
                raw_evidence_id=evidence_id,
                event_type=event_type,
                payload=parsed,
            )
        )

    return AdapterParseResult(
        raw_events=tuple(raw_events),
        normalized_events=tuple(normalized_events),
        capabilities=_detect_capabilities(normalized_events),
    )


def _detect_capabilities(events: Iterable[NormalizedEvent]) -> CapabilityReport:
    persisted_session_id: str | None = None
    has_completion_events = False
    has_command_or_tool_completion_events = False
    has_usage_fields = False
    has_file_change_events = False

    for event in events:
        payload = event.payload
        if event.event_type == "thread.started" and isinstance(payload.get("thread_id"), str):
            persisted_session_id = payload["thread_id"]

        item = payload.get("item")
        item_type = _item_type(item)
        if event.event_type.endswith(".completed"):
            has_completion_events = True
        if event.event_type == "turn.completed" and isinstance(payload.get("usage"), dict):
            has_usage_fields = True
        if _looks_like_command_or_tool_completion(event.event_type, item_type):
            has_command_or_tool_completion_events = True
        if _looks_like_file_change(event.event_type, item_type):
            has_file_change_events = True

    return CapabilityReport(
        persisted_session_id=persisted_session_id,
        has_completion_events=has_completion_events,
        has_command_or_tool_completion_events=has_command_or_tool_completion_events,
        has_usage_fields=has_usage_fields,
        has_file_change_events=has_file_change_events,
    )


def _item_type(item: Any) -> str | None:
    if isinstance(item, dict):
        item_type = item.get("type")
        if isinstance(item_type, str):
            return item_type
    return None


def _looks_like_command_or_tool_completion(event_type: str, item_type: str | None) -> bool:
    if not event_type.endswith(".completed"):
        return False
    marker = f"{event_type} {item_type or ''}".lower()
    return any(name in marker for name in ("tool", "command", "function_call", "local_shell"))


def _looks_like_file_change(event_type: str, item_type: str | None) -> bool:
    marker = f"{event_type} {item_type or ''}".lower()
    return "file" in marker and any(name in marker for name in ("change", "patch", "write"))
