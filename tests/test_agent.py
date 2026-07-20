import os
import sys
import time
from pathlib import Path

from deadman.agent import run_agent_cli
from deadman.store import EvidenceStore


def test_run_agent_cli_returns_child_exit_code(tmp_path: Path) -> None:
    exit_code = run_agent_cli(
        (sys.executable, "-c", "print('agent ok')"),
        workspace=tmp_path,
        hung_timeout_seconds=5.0,
    )

    assert exit_code == 0


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
    assert EvidenceStore(database).count("signals") == 1
    assert EvidenceStore(database).count("action_results") == 1


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
