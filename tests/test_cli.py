from typer.testing import CliRunner

from apps.cli import app


def test_baseline_cli_reports_unimplemented_status() -> None:
    result = CliRunner().invoke(app)

    assert result.exit_code == 0
    assert result.stdout == "Deadman is initialized. Feature commands are not implemented yet.\n"
