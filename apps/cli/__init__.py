"""The current Deadman command-line entry point."""

from pathlib import Path

import typer

from deadman.detectors.replay import replay_hung_process_fixture

app = typer.Typer(add_completion=False, no_args_is_help=False)


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """Report the baseline status when no command is selected."""
    if ctx.invoked_subcommand is None:
        typer.echo("Deadman is initialized. Feature commands are not implemented yet.")


@app.command()
def replay(path: Path) -> None:
    """Replay a deterministic fixture without live Codex or OpenAI calls."""
    signal = replay_hung_process_fixture(path)
    if signal is None:
        typer.echo("No signals detected.")
        return

    idle_seconds = signal.details.get("idle_seconds", "unknown")
    pid = signal.details.get("pid", "unknown")
    typer.echo(
        f"{signal.kind.value} {signal.evidence_ids[0]} pid={pid} idle_seconds={idle_seconds}"
    )


def main() -> None:
    """Console script entry point."""
    app()
