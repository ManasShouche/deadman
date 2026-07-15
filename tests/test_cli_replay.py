from typer.testing import CliRunner

from apps.cli import app


def test_replay_reports_hung_process_fixture() -> None:
    result = CliRunner().invoke(app, ["replay", "scenarios/recordings/hung-process.jsonl"])

    assert result.exit_code == 0
    assert result.stdout == "HUNG_PROCESS proc_001 pid=101 idle_seconds=65.0\n"
