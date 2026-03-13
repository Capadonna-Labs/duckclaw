import sys
import os
import subprocess
import click
from pathlib import Path

@click.group()
def cli():
    """DuckClaw Operations CLI - Cross-platform (Win/Lin/Mac)"""
    pass

@cli.command()
@click.option("--port", default=8000, help="Port to run the API gateway")
def serve(port):
    """Start the DuckClaw API Gateway"""
    click.echo(f"Starting API Gateway on port {port}...")
    # Cross-platform way to run uvicorn
    try:
        subprocess.run(["uvicorn", "duckclaw.api.gateway:app", "--host", "0.0.0.0", "--port", str(port)], check=True)
    except Exception as e:
        click.echo(f"Error starting server: {e}")

@cli.command()
@click.option("--name", default="DuckClaw", help="Name of the service")
def status(name):
    """Show status of DuckClaw services (PM2 or Docker)"""
    # Try PM2 first
    try:
        subprocess.run(["pm2", "status", name], check=False)
    except FileNotFoundError:
        # Fallback to docker
        click.echo("PM2 not found. Checking Docker containers...")
        subprocess.run(["docker", "ps", "--filter", f"name={name}"], check=False)

@cli.command()
def setup():
    """Run the interactive setup wizard (Cross-platform)"""
    # Logic from scripts/duckclaw_setup_wizard.py would be ported here
    click.echo("Running setup wizard...")
    # ... implementation ...

def _entrypoint():
    cli()

if __name__ == "__main__":
    _entrypoint()
