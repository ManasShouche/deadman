import json

from deadman.adapter import parse_jsonl_lines


def test_parse_jsonl_lines_detects_observed__capabilities() -> None:
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "session-123"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10}}),
    ]

    result = parse_jsonl_lines(lines)

    assert result.capabilities.persisted_session_id == "session-123"
    assert result.capabilities.has_completion_events is True
    assert result.capabilities.has_usage_fields is True
    assert result.capabilities.has_command_or_tool_completion_events is False
    assert [event.event_type for event in result.raw_events] == [
        "thread.started",
        "item.completed",
        "turn.completed",
    ]


def test_parse_jsonl_lines_retains_malformed_and_unknown_events() -> None:
    result = parse_jsonl_lines(
        [
            "{not-json",
            json.dumps({"type": "future.event", "payload": {"kept": True}}),
            json.dumps(["not", "an", "object"]),
        ]
    )

    assert result.raw_events[0].event_type == "malformed_json"
    assert result.raw_events[0].parse_error is not None
    assert result.raw_events[1].event_type == "future.event"
    assert result.raw_events[1].parsed == {"type": "future.event", "payload": {"kept": True}}
    assert result.raw_events[2].event_type == "non_object_json"
    assert len(result.normalized_events) == 1


def test_parse_jsonl_lines_detects_tool_and_file_capabilities_when_present() -> None:
    result = parse_jsonl_lines(
        [
            json.dumps({"type": "item.completed", "item": {"type": "tool_call"}}),
            json.dumps({"type": "file_change.completed", "item": {"type": "patch_write"}}),
        ]
    )

    assert result.capabilities.has_command_or_tool_completion_events is True
    assert result.capabilities.has_file_change_events is True
