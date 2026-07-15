import sys

import pytest

from deadman.adapter import run_and_capture_jsonl


def test_run_and_capture_jsonl_uses_argument_array_and_retains_stderr() -> None:
    script = (
        "import json, sys; "
        "print(json.dumps({'type':'thread.started','thread_id':'s1'})); "
        "print('warning', file=sys.stderr)"
    )

    result = run_and_capture_jsonl([sys.executable, "-c", script])

    assert result.returncode == 0
    assert result.argv[:2] == (sys.executable, "-c")
    assert result.stderr == "warning\n"
    assert result.parsed.capabilities.persisted_session_id == "s1"


def test_run_and_capture_jsonl_rejects_empty_argv() -> None:
    with pytest.raises(ValueError, match="argv must not be empty"):
        run_and_capture_jsonl([])


def test_run_and_capture_jsonl_does_not_shell_interpolate() -> None:
    script = "import sys; print(sys.argv[1])"

    result = run_and_capture_jsonl([sys.executable, "-c", script, "$(echo unsafe)"])

    assert result.returncode == 0
    assert result.stdout_jsonl == ("$(echo unsafe)",)
    assert result.parsed.raw_events[0].event_type == "malformed_json"
