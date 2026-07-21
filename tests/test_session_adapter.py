import json
from pathlib import Path

from deadman.adapter import discover_cli_sessions, ingest_session, select_cli_session
from deadman.domain import SessionEventKind
from deadman.store import EvidenceStore


def test_discover_cli_sessions_filters_source_and_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    _write_rollout(codex_home, "cli-match", workspace, source="cli")
    _write_rollout(codex_home, "exec-match", workspace, source="exec")
    _write_rollout(codex_home, "cli-other", tmp_path / "other", source="cli")

    candidates = discover_cli_sessions(workspace, codex_home=codex_home)

    assert [candidate.session_id for candidate in candidates] == ["cli-match"]
    assert select_cli_session("cli-match", workspace, codex_home=codex_home) == candidates[0]


def test_ingest_session_is_idempotent_and_capability_gated(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    path = _write_rollout(codex_home, "session-1", workspace)
    _append_events(
        path,
        [
            _event_msg("task_started"),
            _event_msg("token_count"),
            _response_item("custom_tool_call"),
            _response_item("custom_tool_call_output"),
            _event_msg("task_complete"),
        ],
    )
    candidate = discover_cli_sessions(workspace, codex_home=codex_home)[0]
    store = EvidenceStore(tmp_path / "deadman.sqlite")

    first = ingest_session(candidate, store)
    second = ingest_session(candidate, store)

    assert first.new_event_count == 6
    assert first.event_count == 6
    assert first.turn_state == "idle"
    assert first.capabilities == ("usage", "tool_calls", "completion")
    assert first.ownership.value == "unproven"
    assert second.new_event_count == 0
    assert second.event_count == 6


def test_ingest_session_waits_for_complete_line_and_preserves_unknowns(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    path = _write_rollout(codex_home, "session-1", workspace)
    candidate = discover_cli_sessions(workspace, codex_home=codex_home)[0]
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    ingest_session(candidate, store)

    with path.open("ab") as handle:
        handle.write(b'{"type":"future_event","payload":{"value":1}}')
    partial = ingest_session(candidate, store)
    with path.open("ab") as handle:
        handle.write(b"\n{broken\n")
    completed = ingest_session(candidate, store)

    assert partial.new_event_count == 0
    assert completed.new_event_count == 2
    assert set(store.session_event_kinds("session-1")) >= {
        SessionEventKind.UNKNOWN.value,
        SessionEventKind.MALFORMED.value,
    }


def test_ingest_session_starts_new_generation_after_truncation(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    path = _write_rollout(codex_home, "session-1", workspace)
    _append_events(path, [_event_msg("task_started"), _event_msg("task_complete")])
    candidate = discover_cli_sessions(workspace, codex_home=codex_home)[0]
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    first = ingest_session(candidate, store)

    path.write_text(_session_meta("session-1", workspace), encoding="utf-8")
    second = ingest_session(candidate, store)

    assert first.event_count == 3
    assert second.new_event_count == 1
    assert second.event_count == 4
    assert store.latest_event_source(path.resolve()).generation == 1  # type: ignore[union-attr]


def test_sanitized_cli_contract_fixture_replays_equivalently(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    target = codex_home / "sessions" / "2026" / "07" / "18" / "fixture.jsonl"
    target.parent.mkdir(parents=True)
    fixture = Path("scenarios/recordings/codex-session-cli-0.144.4.jsonl")
    events = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    events[0]["payload"]["cwd"] = str(workspace)
    target.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    candidate = discover_cli_sessions(workspace, codex_home=codex_home)[0]

    snapshot = ingest_session(candidate, EvidenceStore(tmp_path / "fixture.sqlite"))

    assert snapshot.event_count == 6
    assert snapshot.turn_state == "idle"
    assert snapshot.capabilities == ("usage", "tool_calls", "completion")


def _write_rollout(
    codex_home: Path,
    session_id: str,
    workspace: Path,
    *,
    source: str = "cli",
) -> Path:
    path = codex_home / "sessions" / "2026" / "07" / "18" / f"rollout-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_session_meta(session_id, workspace, source=source), encoding="utf-8")
    return path


def _session_meta(session_id: str, workspace: Path, *, source: str = "cli") -> str:
    return json.dumps(
        {
            "timestamp": "2026-07-18T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": str(workspace),
                "source": source,
                "cli_version": "0.144.4",
            },
        }
    ) + "\n"


def _event_msg(event_type: str) -> dict[str, object]:
    return {
        "timestamp": "2026-07-18T10:00:01Z",
        "type": "event_msg",
        "payload": {"type": event_type},
    }


def _response_item(item_type: str) -> dict[str, object]:
    return {
        "timestamp": "2026-07-18T10:00:02Z",
        "type": "response_item",
        "payload": {"type": item_type},
    }


def _append_events(path: Path, events: list[dict[str, object]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
