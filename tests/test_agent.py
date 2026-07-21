import os
import sys
import time
from pathlib import Path

import pytest

from deadman.agent import run_agent_cli
from deadman.domain import ProcessObservation
from deadman.monitor import is_baseline_descendant
from deadman.store import EvidenceStore

requires_posix_pty = pytest.mark.skipif(os.name != "posix", reason="requires a POSIX PTY")


@requires_posix_pty
def test_run_agent_cli_returns_child_exit_code(tmp_path: Path) -> None:
    exit_code = run_agent_cli(
        (sys.executable, "-c", "print('agent ok')"),
        workspace=tmp_path,
        hung_timeout_seconds=5.0,
    )

    assert exit_code == 0


@requires_posix_pty
def test_run_agent_cli_sets_child_terminal_dimensions(tmp_path: Path) -> None:
    output = tmp_path / "size.txt"
    script = (
        "import os, shutil, sys; "
        "size = shutil.get_terminal_size(); "
        f"open({str(output)!r}, 'w').write("
        "f'{size.columns} {size.lines} {os.environ.get(\"COLUMNS\")} {os.environ.get(\"LINES\")}')"
    )

    exit_code = run_agent_cli(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        hung_timeout_seconds=5.0,
    )

    columns, rows, env_columns, env_rows = output.read_text().split()
    assert exit_code == 0
    assert int(columns) >= 80
    assert int(rows) >= 24
    assert int(env_columns) >= 80
    assert int(env_rows) >= 24


@requires_posix_pty
def test_run_agent_cli_default_database_uses_git_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    subdir = root / "nested"
    subdir.mkdir(parents=True)
    (root / ".git").mkdir()

    exit_code = run_agent_cli(
        (sys.executable, "-c", "print('agent root db')"),
        workspace=subdir,
        hung_timeout_seconds=5.0,
    )

    assert exit_code == 0
    assert (root / ".deadman" / "deadman.sqlite").exists()


def test_interactive_codex_prompt_text_never_marks_codex_as_recoverable() -> None:
    observation = ProcessObservation(
        evidence_id="codex",
        root_pid=100,
        pid=101,
        parent_pid=100,
        command_line=(
            "/opt/homebrew/bin/codex",
            "--sandbox",
            "workspace-write",
            "Run a Python diagnostic command that waits forever",
        ),
        is_running=True,
        is_descendant=True,
        observed_at=1.0,
    )

    assert is_baseline_descendant(observation)


def _observation(command_line: tuple[str, ...]) -> ProcessObservation:
    return ProcessObservation(
        evidence_id="obs",
        root_pid=100,
        pid=101,
        parent_pid=100,
        command_line=command_line,
        is_running=True,
        is_descendant=True,
        observed_at=1.0,
    )


def test_real_codex_helper_processes_are_baseline() -> None:
    # Observed shapes from a live Codex 0.144.4 process tree.
    helpers = [
        ("node", "./mcp/server.mjs"),
        ("/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl",),
        ("/opt/homebrew/lib/node_modules/.../bin/codex-code-mode-host",),
        ("/opt/homebrew/lib/node_modules/.../vendor/aarch64-apple-darwin/bin/codex",),
    ]
    for command_line in helpers:
        assert is_baseline_descendant(_observation(command_line)), command_line


def test_user_commands_are_recoverable_not_baseline() -> None:
    user_commands = [
        ("/bin/sleep", "300"),
        ("bash", "-lc", "sleep 300"),
        ("python", "-c", "import time; time.sleep(9)"),
        ("/usr/local/bin/some-service", "--serve"),
    ]
    for command_line in user_commands:
        assert not is_baseline_descendant(_observation(command_line)), command_line


@requires_posix_pty
def test_run_agent_cli_auto_recovers_hung_child(tmp_path: Path) -> None:
    script = (
        "import subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "raise SystemExit(child.wait())"
    )
    database = tmp_path / "deadman.sqlite"

    exit_code = run_agent_cli(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        database_path=database,
        hung_timeout_seconds=0.2,
        auto_recover=True,
    )

    assert exit_code != 0
    store = EvidenceStore(database)
    assert store.count("signals") == 1
    assert store.count("action_results") == 1
    assert store.count("incidents") == 1
    assert store.count("diagnoses") == 1
    assert store.count("verification_results") == 1


@requires_posix_pty
def test_run_agent_cli_detects_hung_child_despite_parent_chatter(tmp_path: Path) -> None:
    script = (
        "import subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "\nwhile child.poll() is None:\n"
        "    print('waiting for background terminal', flush=True)\n"
        "    time.sleep(0.05)\n"
        "raise SystemExit(child.returncode)"
    )
    database = tmp_path / "deadman.sqlite"

    exit_code = run_agent_cli(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        database_path=database,
        hung_timeout_seconds=0.2,
        auto_recover=True,
    )

    assert exit_code != 0
    assert EvidenceStore(database).count("signals") == 1
    assert EvidenceStore(database).count("action_results") == 1


@requires_posix_pty
def test_run_agent_cli_auto_recovery_stops_inner_sleep_child(tmp_path: Path) -> None:
    grandchild_pid_file = tmp_path / "grandchild.pid"
    inner_script = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(grandchild_pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    script = (
        "import subprocess, sys; "
        "child = subprocess.Popen(["
        f"sys.executable, '-c', {inner_script!r}"
        "]); "
        "raise SystemExit(child.wait())"
    )
    database = tmp_path / "deadman.sqlite"

    exit_code = run_agent_cli(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        database_path=database,
        hung_timeout_seconds=0.2,
        auto_recover=True,
    )

    grandchild_pid = int(grandchild_pid_file.read_text())
    assert exit_code != 0
    assert EvidenceStore(database).count("signals") == 1
    assert EvidenceStore(database).count("action_results") == 1
    time.sleep(0.1)
    assert not _pid_is_running(grandchild_pid)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
