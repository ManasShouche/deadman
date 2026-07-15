"""The current Deadman command-line entry point."""

import typer

app = typer.Typer(add_completion=False, no_args_is_help=False)


@app.callback(invoke_without_command=True)
def main() -> None:
    """Report the D0 baseline status."""
    typer.echo("Deadman is initialized. Feature commands are not implemented yet.")
