"""The current Deadman command-line entry point."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from deadman.adapter import discover_cli_sessions, select_cli_session
from deadman.agent import run_agent_cli
from deadman.config import load_openai_credentials
from deadman.detectors.replay import replay_fixture
from deadman.diagnosis import FakeDiagnosisClient, build_default_openai_diagnosis_client
from deadman.report import render_incident_report
from deadman.run import run_supervised_command
from deadman.store import EvidenceStore
from deadman.ui import (
    render_demo_dashboard,
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

    credentials = load_openai_credentials(Path.cwd())
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
        workspace=Path.cwd(),
        database_path=database,
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
    raise typer.Exit(
        run_agent_cli(
            argv,
            workspace=Path.cwd(),
            database_path=database,
            hung_timeout_seconds=hung_timeout,
            auto_recover=auto_recover,
        )
    )


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
    workspace = Path.cwd()
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

    db_path = database or workspace / ".deadman" / "deadman.sqlite"
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

    credentials = load_openai_credentials(Path.cwd())
    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("OpenAI API", "ready" if credentials.available else "not configured")
    table.add_row("Credential source", credentials.source)
    table.add_row("Project env", credentials.env_file)
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
