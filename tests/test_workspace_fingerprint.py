import subprocess
from pathlib import Path

from deadman.monitor import workspace_progress_fingerprint


def test_workspace_progress_fingerprint_changes_for_modified_tracked_file(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("one", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "initial")

    before = workspace_progress_fingerprint(tmp_path)
    tracked.write_text("two", encoding="utf-8")
    after = workspace_progress_fingerprint(tmp_path)

    assert before != after


def test_workspace_progress_fingerprint_ignores_untracked_file_contents(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    before = workspace_progress_fingerprint(tmp_path)
    (tmp_path / "untracked.txt").write_text("one", encoding="utf-8")
    middle = workspace_progress_fingerprint(tmp_path)
    (tmp_path / "untracked.txt").write_text("two", encoding="utf-8")
    after = workspace_progress_fingerprint(tmp_path)

    assert before != middle
    assert middle == after


def test_workspace_progress_fingerprint_includes_test_and_command_summary(tmp_path: Path) -> None:
    _git(tmp_path, "init")

    one = workspace_progress_fingerprint(tmp_path, test_summary="1 failed")
    two = workspace_progress_fingerprint(tmp_path, test_summary="0 failed")
    three = workspace_progress_fingerprint(tmp_path, target_exit_result="exit 1")

    assert one != two
    assert one != three


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
