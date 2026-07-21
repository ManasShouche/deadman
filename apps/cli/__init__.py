"""The current Deadman command-line entry point."""

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from deadman.adapter import discover_cli_sessions, select_cli_session
from deadman.agent import run_agent_cli
from deadman.attach import (
    LiveCodexProcess,
    discover_live_codex_processes,
    run_attach_supervisor,
)
from deadman.config import load_openai_credentials
from deadman.detectors.replay import replay_fixture
from deadman.diagnosis import FakeDiagnosisClient, build_default_openai_diagnosis_client
from deadman.paths import default_database_path, project_root
from deadman.platforms import supports_pty_supervision
from deadman.recovery import DiagnosisClient
from deadman.report import render_incident_report
from deadman.run import run_supervised_command
from deadman.store import EvidenceStore
from deadman.ui import (
    render_demo_dashboard,
    render_live_codex_processes,
    render_recovery_outcome,
    render_replay_result,
    render_report_panel,
    render_run_summary,
    render_session_candidates,
    render_watch_snapshot,
)
from deadman.watch import iter_watch_snapshots

app = typer.Typer(add_completion=False, no_args_is_help=False)
config_app = typer.Typer(help="Check local Deadman configuration.")
app.add_typer(config_app, name="config")
console = Console()


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """Report the baseline status when no command is selected."""
    if ctx.invoked_subcommand is None:
        typer.echo("Deadman is initialized. Feature commands are not implemented yet.")


@app.command()
def replay(path: Path) -> None:
    """Replay a deterministic fixture without live Codex or OpenAI calls."""
    incident = replay_fixture(path)
    if incident is None:
        typer.echo("No signals detected.")
        return

    console.print(render_replay_result(incident))


@app.command()
def demo() -> None:
    """Run all bundled deterministic replay demonstrations."""
    incidents = []
    for fixture in _demo_fixtures():
        incident = replay_fixture(fixture)
        if incident is None:
            typer.echo(f"{fixture.stem}: NO_SIGNAL")
            continue
        incidents.append(incident)
    console.print(render_demo_dashboard(incidents))


@app.command()
def report(incident_id: str) -> None:
    """Render a terminal report for a bundled replay incident."""
    path = Path("scenarios/recordings") / f"{incident_id}.jsonl"
    incident = replay_fixture(path)
    if incident is None:
        raise typer.BadParameter(f"no replay incident found for {incident_id}")
    console.print(render_report_panel(render_incident_report(incident)))


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(
    ctx: typer.Context,
    database: Annotated[
        Path | None,
        typer.Option(
            "--database",
            help="SQLite database path. Defaults to .deadman/deadman.sqlite.",
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Optional supervised command timeout in seconds."),
    ] = None,
    hung_timeout: Annotated[
        float | None,
        typer.Option(
            "--hung-timeout",
            help="Enable live hung-child detection after this many idle seconds.",
        ),
    ] = None,
    auto_recover: Annotated[
        bool,
        typer.Option(
            "--auto-recover",
            help="Allow policy-approved deterministic recovery actions without prompting.",
        ),
    ] = False,
    diagnosis: Annotated[
        str,
        typer.Option(
            "--diagnosis",
            help="Diagnosis backend for live incidents: auto, fake, or openai.",
        ),
    ] = "auto",
    model: Annotated[
        str,
        typer.Option("--model", help="OpenAI model used when --diagnosis openai is selected."),
    ] = "gpt-5.6",
    resume_after_recovery: Annotated[
        bool,
        typer.Option(
            "--resume-after-recovery",
            help="After verified recovery, run codex exec resume with diagnosis guidance.",
        ),
    ] = False,
) -> None:
    """Run and record a supervised command after --."""
    argv = tuple(ctx.args)
    if not argv:
        raise typer.BadParameter("provide a command after --")
    if diagnosis not in {"auto", "fake", "openai"}:
        raise typer.BadParameter("--diagnosis must be auto, fake, or openai")
    workspace = project_root(Path.cwd())
    db_path = database or default_database_path(workspace)
    _print_startup(db_path, auto_recover=auto_recover)
    credentials = load_openai_credentials(workspace)
    use_openai = diagnosis == "openai" or (diagnosis == "auto" and credentials.available)
    if diagnosis == "openai" and not credentials.available:
        raise typer.BadParameter(
            "live OpenAI diagnosis requires OPENAI_API_KEY in the environment or project .env"
        )
    diagnosis_client = (
        build_default_openai_diagnosis_client(model=model)
        if use_openai
        else FakeDiagnosisClient()
    )
    diagnosis_backend = (
        f"openai ({credentials.source})" if use_openai else "fixture fallback (no API key)"
    )

    summary = run_supervised_command(
        argv,
        workspace=workspace,
        database_path=db_path,
        timeout_seconds=timeout,
        auto_recover=auto_recover,
        hung_timeout_seconds=hung_timeout,
        diagnosis_client=diagnosis_client,
        diagnosis_backend=diagnosis_backend,
        resume_after_recovery=resume_after_recovery,
    )
    console.print(render_run_summary(summary))


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def agent(
    ctx: typer.Context,
    database: Annotated[
        Path | None,
        typer.Option(
            "--database",
            help="SQLite database path. Defaults to .deadman/deadman.sqlite.",
        ),
    ] = None,
    hung_timeout: Annotated[
        float,
        typer.Option("--hung-timeout", help="Idle seconds before a child process is hung."),
    ] = 60.0,
    auto_recover: Annotated[
        bool,
        typer.Option(
            "--auto-recover",
            help="Terminate proven hung descendants while the interactive session keeps running.",
        ),
    ] = False,
) -> None:
    """Run an interactive coding-agent CLI in a supervised PTY."""
    argv = tuple(ctx.args)
    if not argv:
        raise typer.BadParameter("provide an interactive command after --")
    if not supports_pty_supervision():
        raise typer.BadParameter(
            "deadman agent requires a POSIX PTY; on Windows, start Codex normally "
            "and use deadman attach from the same repository"
        )
    workspace = project_root(Path.cwd())
    db_path = database or default_database_path(workspace)
    _print_startup(db_path, auto_recover=auto_recover)
    raise typer.Exit(
        run_agent_cli(
            argv,
            workspace=workspace,
            database_path=db_path,
            hung_timeout_seconds=hung_timeout,
            auto_recover=auto_recover,
        )
    )


@app.command()
def attach(
    pid: Annotated[
        int | None,
        typer.Option("--pid", help="Attach to a specific Codex PID instead of prompting."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(
            "--database",
            help="SQLite database path. Defaults to .deadman/deadman.sqlite.",
        ),
    ] = None,
    hung_timeout: Annotated[
        float,
        typer.Option("--hung-timeout", help="Idle seconds before a descendant is hung."),
    ] = 60.0,
    auto_recover: Annotated[
        bool,
        typer.Option(
            "--auto-recover",
            help="Terminate proven hung descendants of the attached Codex process.",
        ),
    ] = False,
    diagnosis: Annotated[
        str,
        typer.Option("--diagnosis", help="Diagnosis backend: auto, fake, or openai."),
    ] = "auto",
    model: Annotated[
        str,
        typer.Option("--model", help="OpenAI model used when --diagnosis openai is selected."),
    ] = "gpt-5.6",
    poll_interval: Annotated[
        float,
        typer.Option("--poll-interval", help="Seconds between descendant observations."),
    ] = 0.5,
) -> None:
    """Attach to a Codex session started in another terminal in this repository."""

    if poll_interval <= 0:
        raise typer.BadParameter("--poll-interval must be greater than zero")
    workspace = project_root(Path.cwd())
    db_path = database or default_database_path(workspace)
    _print_startup(db_path, auto_recover=auto_recover)

    processes = discover_live_codex_processes(
        workspace,
        exclude_pids=frozenset({os.getpid(), os.getppid()}),
    )
    if not processes:
        raise typer.BadParameter(
            "no live Codex process found in this repository; start Codex here first"
        )

    selected = _select_live_process(processes, pid=pid)
    console.print(render_live_codex_processes([selected]))
    if not auto_recover:
        console.print(
            "[deadman] approval mode: hung descendants are reported, not terminated. "
            "Re-run with --auto-recover to act."
        )

    diagnosis_client = _resolve_diagnosis_client(workspace, diagnosis=diagnosis, model=model)
    try:
        incidents = run_attach_supervisor(
            selected,
            workspace=workspace,
            database_path=db_path,
            diagnosis_client=diagnosis_client,
            hung_timeout_seconds=hung_timeout,
            auto_recover=auto_recover,
            poll_interval_seconds=poll_interval,
            on_status=lambda message: console.print(f"[deadman] {message}"),
            on_recovery=lambda outcome: console.print(render_recovery_outcome(outcome)),
        )
    except KeyboardInterrupt:
        console.print("[deadman] detached; Codex session left running")
        return
    console.print(f"[deadman] supervision ended; incidents opened: {incidents}")


@app.command()
def watch(
    session: Annotated[
        str | None,
        typer.Option("--session", help="Persisted interactive Codex session id to pair."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(
            "--database",
            help="SQLite database path. Defaults to .deadman/deadman.sqlite.",
        ),
    ] = None,
    poll_interval: Annotated[
        float,
        typer.Option("--poll-interval", help="Seconds between persisted-session reads."),
    ] = 0.5,
    once: Annotated[
        bool,
        typer.Option("--once", help="Ingest current events, render once, and exit."),
    ] = False,
) -> None:
    """Observe an explicitly paired interactive Codex session without process control."""

    if poll_interval <= 0:
        raise typer.BadParameter("--poll-interval must be greater than zero")
    workspace = project_root(Path.cwd())
    db_path = database or default_database_path(workspace)
    _print_startup(db_path, auto_recover=False)
    if session is not None:
        try:
            candidate = select_cli_session(session, workspace)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        candidates = discover_cli_sessions(workspace)
        if not candidates:
            raise typer.BadParameter("no persisted interactive Codex sessions match this workspace")
        if not sys.stdin.isatty():
            ids = ", ".join(candidate.session_id for candidate in candidates[:10])
            raise typer.BadParameter(f"provide --session; matching sessions: {ids}")
        console.print(render_session_candidates(candidates[:10]))
        selection = typer.prompt("Session number", type=int)
        if selection < 1 or selection > min(len(candidates), 10):
            raise typer.BadParameter("session number is outside the displayed range")
        candidate = candidates[selection - 1]

    snapshots = iter_watch_snapshots(
        candidate,
        EvidenceStore(db_path),
        poll_interval_seconds=poll_interval,
    )
    try:
        for snapshot in snapshots:
            console.print(render_watch_snapshot(snapshot))
            if once:
                break
    except KeyboardInterrupt:
        return


@config_app.command("check")
def config_check() -> None:
    """Report credential readiness without displaying secret values."""

    workspace = project_root(Path.cwd())
    db_path = default_database_path(workspace)
    credentials = load_openai_credentials(workspace)
    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("OpenAI API", "ready" if credentials.available else "not configured")
    table.add_row("Credential source", credentials.source)
    table.add_row("Project env", credentials.env_file)
    table.add_row("SQLite", str(db_path))
    table.add_row("Offline replay", "ready")
    table.add_row("Codex TUI auth", "separate; never read by Deadman")
    console.print(table)


def main() -> None:
    """Console script entry point."""
    app()


def _demo_fixtures() -> tuple[Path, ...]:
    root = Path("scenarios/recordings")
    return (
        root / "hung-process.jsonl",
        root / "repeated-failure.jsonl",
        root / "session-handoff.jsonl",
    )


def _print_startup(database_path: Path, *, auto_recover: bool) -> None:
    typer.echo(f"SQLite: {database_path}")
    typer.echo(f"Auto recover: {'on' if auto_recover else 'off'}")


def _select_live_process(
    processes: tuple[LiveCodexProcess, ...],
    *,
    pid: int | None,
) -> LiveCodexProcess:
    if pid is not None:
        for process in processes:
            if process.pid == pid:
                return process
        raise typer.BadParameter(f"pid {pid} is not a live Codex process in this repository")
    if len(processes) == 1:
        return processes[0]
    if not sys.stdin.isatty():
        pids = ", ".join(str(process.pid) for process in processes[:10])
        raise typer.BadParameter(f"multiple Codex processes found; pass --pid. Candidates: {pids}")
    console.print(render_live_codex_processes(processes[:10]))
    choice: int = typer.prompt("Process number", type=int)
    if choice < 1 or choice > min(len(processes), 10):
        raise typer.BadParameter("process number is outside the displayed range")
    return processes[choice - 1]


def _resolve_diagnosis_client(
    workspace: Path,
    *,
    diagnosis: str,
    model: str,
) -> DiagnosisClient:
    if diagnosis not in {"auto", "fake", "openai"}:
        raise typer.BadParameter("--diagnosis must be auto, fake, or openai")
    credentials = load_openai_credentials(workspace)
    use_openai = diagnosis == "openai" or (diagnosis == "auto" and credentials.available)
    if diagnosis == "openai" and not credentials.available:
        raise typer.BadParameter(
            "live OpenAI diagnosis requires OPENAI_API_KEY in the environment or project .env"
        )
    if use_openai:
        return build_default_openai_diagnosis_client(model=model)
    return FakeDiagnosisClient()
