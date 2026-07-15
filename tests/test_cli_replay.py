from typer.testing import CliRunner

from apps.cli import app


def test_replay_reports_hung_process_fixture() -> None:
    result = CliRunner().invoke(app, ["replay", "scenarios/recordings/hung-process.jsonl"])

    assert result.exit_code == 0
    assert "HUNG_PROCESS" in result.stdout
    assert "TERMINATE_DESCENDANT_PROCESS" in result.stdout
    assert "RESOLVED" in result.stdout


def test_demo_runs_all_bundled_fixtures() -> None:
    result = CliRunner().invoke(app, ["demo"])

    assert result.exit_code == 0
    assert "Deadman demo" in result.stdout
    assert "hung-process" in result.stdout
    assert "repeated-failure" in result.stdout
    assert "session-handoff" in result.stdout


def test_report_renders_bundled_incident() -> None:
    result = CliRunner().invoke(app, ["report", "repeated-failure"])

    assert result.exit_code == 0
    assert "Incident: repeated-failure" in result.stdout
    assert "Signal: REPEATED_FAILURE" in result.stdout
