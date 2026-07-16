"""The current Deadman command-line entry point."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from deadman.detectors.replay import replay_fixture
from deadman.diagnosis import FakeDiagnosisClient, build_default_openai_diagnosis_client
from deadman.report import render_incident_report
from deadman.run import run_supervised_command
from deadman.ui import (
    render_demo_dashboard,
    render_replay_result,
    render_report_panel,
    render_run_summary,
)

app = typer.Typer(add_completion=False, no_args_is_help=False)
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
            help="Diagnosis backend for live incidents: fake or openai.",
        ),
    ] = "fake",
    model: Annotated[
        str,
        typer.Option("--model", help="OpenAI model used when --diagnosis openai is selected."),
    ] = "gpt-5.6",
) -> None:
    """Run and record a supervised command after --."""
    argv = tuple(ctx.args)
    if not argv:
        raise typer.BadParameter("provide a command after --")
    if diagnosis not in {"fake", "openai"}:
        raise typer.BadParameter("--diagnosis must be fake or openai")

    diagnosis_client = (
        build_default_openai_diagnosis_client(model=model)
        if diagnosis == "openai"
        else FakeDiagnosisClient()
    )

    summary = run_supervised_command(
        argv,
        workspace=Path.cwd(),
        database_path=database,
        timeout_seconds=timeout,
        auto_recover=auto_recover,
        hung_timeout_seconds=hung_timeout,
        diagnosis_client=diagnosis_client,
    )
    console.print(render_run_summary(summary))


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
