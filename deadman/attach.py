"""Attach supervision: recover a Codex session launched in another terminal.

Managed mode (`deadman run`/`deadman agent`) owns the Codex process because
Deadman spawned it. Attach mode instead discovers a Codex process the user
started independently in the same repository, proves ownership through the OS
process table (not a persisted session file), and runs the same bounded
hung-descendant recovery. Proving the live root PID is what lets attach mode
act where observe-only `deadman watch` cannot.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psutil

from deadman.adapter import discover_cli_sessions
from deadman.domain import SessionMode, SessionOwnership, SessionRecord
from deadman.monitor import DescendantTracker
from deadman.paths import project_root
from deadman.recovery import DiagnosisClient, RecoveryOutcome, recover_hung_descendant
from deadman.store import EvidenceStore

PROCESS_LOOKUP_ERRORS = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
    PermissionError,
)
STATUS_INTERVAL_SECONDS = 6.0


@dataclass(frozen=True)
class LiveCodexProcess:
    """A running Codex process discovered inside the watched repository."""

    pid: int
    cwd: Path
    command_line: tuple[str, ...]
    create_time: float
    session_id: str | None

    @property
    def label(self) -> str:
        return self.session_id or f"pid:{self.pid}"


def discover_live_codex_processes(
    workspace: Path,
    *,
    codex_home: Path | None = None,
    exclude_pids: frozenset[int] = frozenset(),
) -> tuple[LiveCodexProcess, ...]:
    """Find running Codex processes whose working directory is in this repo."""

    repo = project_root(workspace)
    matches: list[LiveCodexProcess] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        pid = process.info.get("pid")
        if pid is None or pid in exclude_pids:
            continue
        if not _looks_like_codex(process.info.get("name"), process.info.get("cmdline")):
            continue
        try:
            cwd = Path(process.cwd()).resolve()
        except PROCESS_LOOKUP_ERRORS:
            continue
        if not _within_repo(cwd, repo):
            continue
        matches.append(
            LiveCodexProcess(
                pid=int(pid),
                cwd=cwd,
                command_line=tuple(process.info.get("cmdline") or ()),
                create_time=float(process.info.get("create_time") or 0.0),
                session_id=_correlated_session_id(cwd, codex_home=codex_home),
            )
        )

    # The interactive Codex CLI is a `node <path>/codex` wrapper whose child is
    # the `codex` rust binary, and both share the repo cwd. Collapse a candidate
    # to its top-most matching ancestor so the user picks one process, not a
    # parent/child pair; supervising the ancestor still covers the whole tree.
    matches = _drop_nested_candidates(matches)

    # Newest process first so the default selection is the session just started.
    return tuple(sorted(matches, key=lambda match: match.create_time, reverse=True))


def run_attach_supervisor(
    process: LiveCodexProcess,
    *,
    workspace: Path,
    database_path: Path,
    diagnosis_client: DiagnosisClient,
    hung_timeout_seconds: float,
    auto_recover: bool,
    poll_interval_seconds: float = 0.5,
    on_status: Callable[[str], None] | None = None,
    on_recovery: Callable[[RecoveryOutcome], None] | None = None,
    max_polls: int | None = None,
) -> int:
    """Monitor a discovered Codex root PID and recover proven hung descendants.

    Returns the number of incidents opened. Runs until the Codex process exits,
    ``max_polls`` is reached, or the caller interrupts.
    """

    repo = project_root(workspace)
    store = EvidenceStore(database_path)
    session_id = _register_attach_session(store, process, repo)

    tracker = DescendantTracker(process.pid, hung_timeout_seconds=hung_timeout_seconds)
    recovered_fingerprints: set[str] = set()
    incidents = 0
    polls = 0
    last_status_at = 0.0

    while _root_alive(process.pid):
        if max_polls is not None and polls >= max_polls:
            break
        polls += 1
        outcome = supervise_attached_step(
            store,
            tracker=tracker,
            root_pid=process.pid,
            session_id=session_id,
            diagnosis_client=diagnosis_client,
            auto_recover=auto_recover,
            recovered_fingerprints=recovered_fingerprints,
        )
        if outcome is None:
            # Healthy heartbeat so monitoring is visibly alive between incidents.
            now = time.monotonic()
            if on_status is not None and now - last_status_at >= STATUS_INTERVAL_SECONDS:
                on_status(
                    f"monitoring {tracker.watched_count()} owned descendant(s); "
                    f"baseline ignored={len(tracker.ignored_pids)}; incidents={incidents}"
                )
                last_status_at = now
            time.sleep(poll_interval_seconds)
            continue
        incidents += 1
        if on_recovery is not None:
            on_recovery(outcome)
        elif on_status is not None:
            on_status(f"{outcome.status}: {outcome.message}")

    if on_status is not None:
        on_status("codex session ended" if not _root_alive(process.pid) else "supervision stopped")
    return incidents


def supervise_attached_step(
    store: EvidenceStore,
    *,
    tracker: DescendantTracker,
    root_pid: int,
    session_id: str,
    diagnosis_client: DiagnosisClient,
    auto_recover: bool,
    recovered_fingerprints: set[str],
    now: float | None = None,
) -> RecoveryOutcome | None:
    """Observe descendants once; recover and record if a new hung child is found."""

    moment = time.monotonic() if now is None else now
    signal = tracker.poll(moment)
    _persist_observations(store, tracker, session_id)
    if signal is None or signal.fingerprint in recovered_fingerprints:
        return None

    store.add_signals((signal,), session_id=session_id)
    recovered_fingerprints.add(signal.fingerprint)
    return recover_hung_descendant(
        store,
        session_id=session_id,
        root_pid=root_pid,
        signal=signal,
        diagnosis_client=diagnosis_client,
        auto_recover=auto_recover,
        mode="attach",
    )


def _register_attach_session(
    store: EvidenceStore,
    process: LiveCodexProcess,
    repo: Path,
) -> str:
    session_id = f"attach:{process.pid}"
    now = time.time()
    store.upsert_session(
        SessionRecord(
            session_id=session_id,
            external_session_id=process.session_id,
            mode=SessionMode.ATTACH,
            source="codex_cli",
            cwd=str(process.cwd),
            # Ownership is MANAGED here because the live OS process tree proves
            # the root PID; this is stronger evidence than a persisted file.
            ownership=SessionOwnership.MANAGED,
            status="supervising",
            started_at=process.create_time or now,
            last_seen_at=now,
        )
    )
    return session_id


def _persist_observations(
    store: EvidenceStore,
    tracker: DescendantTracker,
    session_id: str,
) -> None:
    if not tracker.observations:
        return
    by_pid = {observation.pid: observation for observation in tracker.observations}
    store.add_process_observations(by_pid.values(), session_id=session_id)


def _drop_nested_candidates(matches: list[LiveCodexProcess]) -> list[LiveCodexProcess]:
    """Drop candidates whose ancestor is also a candidate, keeping the ancestor."""

    candidate_pids = {match.pid for match in matches}
    kept: list[LiveCodexProcess] = []
    for match in matches:
        try:
            ancestor_pids = {parent.pid for parent in psutil.Process(match.pid).parents()}
        except PROCESS_LOOKUP_ERRORS:
            ancestor_pids = set()
        if candidate_pids & ancestor_pids:
            continue
        kept.append(match)
    return kept


def _looks_like_codex(name: str | None, command_line: list[str] | None) -> bool:
    if name and Path(name).name.lower() == "codex":
        return True
    if not command_line:
        return False
    executable = Path(command_line[0]).name.lower()
    if executable == "codex":
        return True
    # `codex exec ...` or a wrapped launch: match a leading codex token.
    return any(Path(token).name.lower() == "codex" for token in command_line[:2])


def _within_repo(cwd: Path, repo: Path) -> bool:
    return cwd == repo or repo in cwd.parents


def _correlated_session_id(cwd: Path, *, codex_home: Path | None) -> str | None:
    candidates = discover_cli_sessions(cwd, codex_home=codex_home)
    if not candidates:
        return None
    return candidates[0].session_id


def _root_alive(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except PROCESS_LOOKUP_ERRORS:
        return False
