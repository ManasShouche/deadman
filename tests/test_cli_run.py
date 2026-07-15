import sys
from pathlib import Path

from typer.testing import CliRunner

from apps.cli import app
from deadman.store import EvidenceStore


def test_cli_run_records_supervised_command(tmp_path: Path) -> None:
    script = (
        "import json; "
        "print(json.dumps({'type':'thread.started','thread_id':'cli-session'})); "
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message'}}))"
    )
    database = tmp_path / "deadman.sqlite"

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--database",
            str(database),
            "--",
            sys.executable,
            "-c",
            script,
        ],
    )

    assert result.exit_code == 0
    assert "completed" in result.stdout
    assert "cli-session" in result.stdout
    assert EvidenceStore(database).count("raw_events") == 2


def test_cli_run_requires_command_after_separator() -> None:
    result = CliRunner().invoke(app, ["run"])

    assert result.exit_code != 0
    assert "provide a command after --" in result.output
