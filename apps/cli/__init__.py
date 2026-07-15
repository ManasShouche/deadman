"""The current Deadman command-line entry point."""

from pathlib import Path

import typer

from deadman.detectors.replay import replay_fixture
from deadman.report import render_incident_report

app = typer.Typer(add_completion=False, no_args_is_help=False)


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

    typer.echo(
        f"{incident.signal.kind.value} {incident.diagnosis.recommended_action.value} "
        f"{'RESOLVED' if incident.verification.resolved else 'ESCALATED'}"
    )


@app.command()
def demo() -> None:
    """Run all bundled deterministic replay demonstrations."""
    for fixture in _demo_fixtures():
        incident = replay_fixture(fixture)
        if incident is None:
            typer.echo(f"{fixture.stem}: NO_SIGNAL")
            continue
        typer.echo(
            f"{fixture.stem}: {incident.signal.kind.value} -> "
            f"{incident.diagnosis.recommended_action.value} -> "
            f"{'RESOLVED' if incident.verification.resolved else 'ESCALATED'}"
        )


@app.command()
def report(incident_id: str) -> None:
    """Render a terminal report for a bundled replay incident."""
    path = Path("scenarios/recordings") / f"{incident_id}.jsonl"
    incident = replay_fixture(path)
    if incident is None:
        raise typer.BadParameter(f"no replay incident found for {incident_id}")
    typer.echo(render_incident_report(incident))


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
