"""Command-line entry points for local deterministic tools."""

import typer

app = typer.Typer(help="B1500A Test Agent development CLI.")


@app.command()
def status() -> None:
    """Show the current skeleton status."""
    typer.echo("B1500A Test Agent skeleton is installed. Hardware control is not implemented.")
