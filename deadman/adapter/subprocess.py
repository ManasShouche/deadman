"""Subprocess adapter primitives for supervised Codex runs."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from deadman.adapter import AdapterParseResult, parse_jsonl_lines


@dataclass(frozen=True)
class CapturedRun:
    """Captured output from a completed supervised process."""

    argv: tuple[str, ...]
    returncode: int
    stdout_jsonl: tuple[str, ...]
    stderr: str
    parsed: AdapterParseResult


def run_and_capture_jsonl(
    argv: Sequence[str],
    *,
    timeout_seconds: float | None = None,
) -> CapturedRun:
    """Run a command with an argument array and parse stdout as retained JSONL evidence."""

    if not argv:
        raise ValueError("argv must not be empty")

    completed = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )
    stdout_lines = tuple(completed.stdout.splitlines())
    return CapturedRun(
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout_jsonl=stdout_lines,
        stderr=completed.stderr,
        parsed=parse_jsonl_lines(stdout_lines),
    )
