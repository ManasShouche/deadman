import json
from pathlib import Path

from rich.text import Text
from typer.testing import CliRunner

from apps.cli import app


def test_watch_once_ingests_explicit_observe_only_session(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    database = tmp_path / "watch.sqlite"
    _write_session(codex_home, workspace, "watch-1")
    monkeypatch.chdir(workspace)  # type: ignore[attr-defined]

    result = CliRunner().invoke(
        app,
        ["watch", "--session", "watch-1", "--database", str(database), "--once"],
        env={"CODEX_HOME": str(codex_home)},
    )

    assert result.exit_code == 0
    assert "Deadman watch" in result.stdout
    assert "observe-only" in result.stdout
    assert "unproven" in result.stdout
    assert "watch-1" in result.stdout


def test_watch_requires_explicit_session_in_noninteractive_mode(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    _write_session(codex_home, workspace, "watch-1")
    _write_session(codex_home, workspace, "watch-2")
    monkeypatch.chdir(workspace)  # type: ignore[attr-defined]

    result = CliRunner().invoke(
        app,
        ["watch", "--once"],
        env={"CODEX_HOME": str(codex_home)},
        color=True,
    )

    output = Text.from_ansi(result.output).plain
    assert result.exit_code != 0
    assert "provide --session" in output
    assert "watch-1" in output
    assert "watch-2" in output


def test_watch_rejects_session_from_another_workspace(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    codex_home = tmp_path / "codex-home"
    _write_session(codex_home, other, "watch-other")
    monkeypatch.chdir(workspace)  # type: ignore[attr-defined]

    result = CliRunner().invoke(
        app,
        ["watch", "--session", "watch-other", "--once"],
        env={"CODEX_HOME": str(codex_home)},
    )

    assert result.exit_code != 0
    assert "matches" in result.output


def test_watch_help_exposes_no_recovery_option() -> None:
    result = CliRunner().invoke(app, ["watch", "--help"], color=True)

    output = Text.from_ansi(result.output).plain
    assert result.exit_code == 0
    assert "--session" in output
    assert "--auto-recover" not in output


def _write_session(codex_home: Path, workspace: Path, session_id: str) -> None:
    path = codex_home / "sessions" / "2026" / "07" / "18" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "timestamp": "2026-07-18T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": str(workspace),
                "source": "cli",
                "cli_version": "0.144.4",
            },
        },
        {
            "timestamp": "2026-07-18T10:00:01Z",
            "type": "event_msg",
            "payload": {"type": "task_complete"},
        },
    ]
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
