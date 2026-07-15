import json
from pathlib import Path

RECORDING = Path("scenarios/recordings/gate-a-codex-cli-0.144.4.jsonl")


def test_gate_a_recording_is_jsonl_with_observed_capabilities() -> None:
    events = [json.loads(line) for line in RECORDING.read_text().splitlines()]

    assert all(isinstance(event, dict) for event in events)
    assert any(event["type"] == "thread.started" and "thread_id" in event for event in events)
    assert any(event["type"] == "item.completed" for event in events)
    assert any("usage" in event for event in events if event["type"] == "turn.completed")
