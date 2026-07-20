"""Codex subprocess and JSONL adapter components."""

from deadman.adapter.jsonl import AdapterParseResult, parse_jsonl_lines
from deadman.adapter.session import (
    SessionCandidate,
    default_codex_home,
    discover_cli_sessions,
    ingest_session,
    persist_managed_events,
    select_cli_session,
)
from deadman.adapter.subprocess import CapturedRun, run_and_capture_jsonl

__all__ = [
    "AdapterParseResult",
    "CapturedRun",
    "SessionCandidate",
    "default_codex_home",
    "discover_cli_sessions",
    "ingest_session",
    "parse_jsonl_lines",
    "run_and_capture_jsonl",
    "persist_managed_events",
    "select_cli_session",
]
