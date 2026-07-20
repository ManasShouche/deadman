import sys
from pathlib import Path

import pytest
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


def test_cli_run_auto_recovers_hung_child(tmp_path: Path) -> None:
    script = (
        "import json, subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "child.wait(); "
        "print(json.dumps({'type':'thread.started','thread_id':'cli-live'})); "
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message'}}))"
    )
    database = tmp_path / "deadman.sqlite"

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--database",
            str(database),
            "--hung-timeout",
            "0.2",
            "--auto-recover",
            "--diagnosis",
            "fake",
            "--",
            sys.executable,
            "-c",
            script,
        ],
    )

    assert result.exit_code == 0
    assert "recovered" in result.stdout
    assert "HUNG_PROCESS" in result.stdout
    assert "TERMINATE_DESCENDANT_PROCESS" in result.stdout
    assert "RESOLVED" in result.stdout


def test_cli_run_accepts_resume_after_recovery_flag(tmp_path: Path) -> None:
    script = "import json; print(json.dumps({'type':'thread.started','thread_id':'done'}))"
    database = tmp_path / "deadman.sqlite"

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--database",
            str(database),
            "--resume-after-recovery",
            "--",
            sys.executable,
            "-c",
            script,
        ],
    )

    assert result.exit_code == 0
    assert "done" in result.stdout


def test_cli_run_requires_command_after_separator() -> None:
    result = CliRunner().invoke(app, ["run"])

    assert result.exit_code != 0
    assert "provide a command after --" in result.output


def test_cli_run_auto_loads_openai_key_from_project_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-project-test\n", encoding="utf-8")
    script = "import json; print(json.dumps({'type':'thread.started','thread_id':'auto'}))"

    result = CliRunner().invoke(
        app,
        ["run", "--database", str(tmp_path / "db.sqlite"), "--", sys.executable, "-c", script],
        env={"OPENAI_API_KEY": ""},
    )

    assert result.exit_code == 0
    assert "openai (project .env)" in result.stdout


def test_cli_run_auto_uses_visible_fixture_fallback_without_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    script = "import json; print(json.dumps({'type':'thread.started','thread_id':'fallback'}))"

    result = CliRunner().invoke(
        app,
        ["run", "--database", str(tmp_path / "db.sqlite"), "--", sys.executable, "-c", script],
        env={"OPENAI_API_KEY": ""},
    )

    assert result.exit_code == 0
    assert "fixture fallback (no API key)" in result.stdout


def test_cli_run_explicit_openai_requires_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["run", "--diagnosis", "openai", "--", sys.executable, "-c", "pass"],
        env={"OPENAI_API_KEY": "", "HOME": str(tmp_path)},
    )

    assert result.exit_code != 0
    assert "requires OPENAI_API_KEY" in result.output


def test_cli_config_check_reports_replay_ready_without_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        ["config", "check"],
        env={"OPENAI_API_KEY": ""},
    )

    assert result.exit_code == 0
    assert "not configured" in result.stdout
    assert "Offline replay" in result.stdout
    assert "ready" in result.stdout
    assert "never read by Deadman" in result.stdout
