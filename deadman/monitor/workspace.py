"""Workspace progress fingerprinting."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def workspace_progress_fingerprint(
    workspace: Path,
    *,
    test_summary: str | None = None,
    target_exit_result: str | None = None,
) -> str:
    """Hash Git-visible workspace progress without storing file contents."""

    status = _git_lines(workspace, "status", "--porcelain")
    modified_paths = _modified_tracked_paths(status)
    file_hashes = [
        f"{path}:{_file_digest(workspace / path)}"
        for path in modified_paths
        if (workspace / path).is_file()
    ]
    payload = "\n".join(
        [
            "status:",
            *status,
            "files:",
            *sorted(file_hashes),
            f"test_summary:{test_summary or ''}",
            f"target_exit_result:{target_exit_result or ''}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_lines(workspace: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        return []
    return completed.stdout.splitlines()


def _modified_tracked_paths(status_lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in status_lines:
        if len(line) < 4 or line.startswith("??"):
            continue
        paths.append(line[3:])
    return paths


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
