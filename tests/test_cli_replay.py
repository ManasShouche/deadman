from typer.testing import CliRunner

from apps.cli import app


def test_replay_reports_hung_process_fixture() -> None:
    result = CliRunner().invoke(app, ["replay", "scenarios/recordings/hung-process.jsonl"])

    assert result.exit_code == 0
    assert result.stdout == "HUNG_PROCESS TERMINATE_DESCENDANT_PROCESS RESOLVED\n"


def test_demo_runs_all_bundled_fixtures() -> None:
    result = CliRunner().invoke(app, ["demo"])

    assert result.exit_code == 0
    assert result.stdout == (
        "hung-process: HUNG_PROCESS -> TERMINATE_DESCENDANT_PROCESS -> RESOLVED\n"
        "repeated-failure: REPEATED_FAILURE -> CANCEL_AND_RESUME -> RESOLVED\n"
        "session-handoff: SESSION_BUDGET_RISK -> CHECKPOINT_AND_RESPAWN -> RESOLVED\n"
    )


def test_report_renders_bundled_incident() -> None:
    result = CliRunner().invoke(app, ["report", "repeated-failure"])

    assert result.exit_code == 0
    assert "Incident: repeated-failure" in result.stdout
    assert "Signal: REPEATED_FAILURE" in result.stdout
