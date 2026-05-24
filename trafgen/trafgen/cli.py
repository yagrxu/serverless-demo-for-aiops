"""CLI entrypoint for the trafgen traffic generator.

Exposes the `run`, `validate`, and `list_scenarios` subcommands via Typer.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

import typer

from .observability import configure_logging, emit_run_metrics

# Configure structured JSON logging on import
configure_logging()

app = typer.Typer(
    name="trafgen",
    help="Traffic generator for the cat-care AIOps demo.",
    no_args_is_help=True,
)


def _parse_duration(duration_str: str) -> float:
    """Parse a duration string like '30s', '5m', '1h' into seconds.

    Supported formats: Ns, Nm, Nh (e.g., '30s', '5m', '1h', '55m').
    """
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(s|m|h)$", duration_str.strip())
    if not match:
        raise typer.BadParameter(
            f"Invalid duration format: '{duration_str}'. "
            "Use formats like '30s', '5m', '1h'."
        )
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return value
    elif unit == "m":
        return value * 60
    elif unit == "h":
        return value * 3600
    return value


@app.command()
def run(
    target: str = typer.Option("local", help="Target environment: 'local' or 'cloud'"),
    profile: Path = typer.Option(
        Path("profiles/baseline.yaml"),
        help="Path to the traffic profile YAML file",
    ),
    duration: str = typer.Option("5m", help="Run duration (e.g., '30s', '5m', '1h')"),
    rps: float = typer.Option(1.0, help="Aggregate requests per second"),
    seed: Optional[int] = typer.Option(None, help="RNG seed for reproducibility"),
    out_dir: Path = typer.Option(Path("./runs"), help="Output directory for manifest files"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Pick scenarios without making HTTP calls"),
    i_know_what_im_doing: bool = typer.Option(
        False, "--i-know-what-im-doing", help="Allow RPS > 100"
    ),
) -> None:
    """Run the traffic generator against a target environment."""
    # Validate target
    if target not in ("local", "cloud"):
        typer.echo(f"Error: target must be 'local' or 'cloud', got '{target}'", err=True)
        raise typer.Exit(code=1)

    # Validate RPS
    if rps > 100 and not i_know_what_im_doing:
        typer.echo(
            "Error: RPS > 100 requires --i-know-what-im-doing flag. "
            "High RPS can overwhelm the target.",
            err=True,
        )
        raise typer.Exit(code=1)

    if rps <= 0:
        typer.echo("Error: RPS must be > 0", err=True)
        raise typer.Exit(code=1)

    # Parse duration
    try:
        duration_s = _parse_duration(duration)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    # Validate profile exists
    if not profile.exists():
        typer.echo(f"Error: profile not found: {profile}", err=True)
        raise typer.Exit(code=1)

    # Validate profile schema
    try:
        from .config import Profile
        Profile.from_yaml(profile)
    except Exception as e:
        typer.echo(f"Error: invalid profile:\n{e}", err=True)
        raise typer.Exit(code=1)

    # Run
    from . import run_once

    typer.echo(f"trafgen: target={target} rps={rps} duration={duration} seed={seed}")

    try:
        summary = asyncio.run(
            run_once(
                target=target,  # type: ignore[arg-type]
                profile_path=profile,
                rps=rps,
                duration_s=duration_s,
                seed=seed,
                out_dir=out_dir,
                dry_run=dry_run,
            )
        )
        typer.echo(
            f"\ndone. dispatched={summary.total_events} "
            f"errors={summary.total_errors} "
            f"saturation_drops={summary.saturation_drops}"
        )
        # Emit CloudWatch EMF metrics
        emit_run_metrics(summary)
        if summary.scenarios:
            typer.echo("\nPer-scenario stats:")
            for s in summary.scenarios:
                typer.echo(
                    f"  {s.scenario_id}: count={s.count} errors={s.errors} "
                    f"p50={s.p50_ms:.1f}ms p95={s.p95_ms:.1f}ms"
                )
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        raise typer.Exit(code=0)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def validate(
    profile_path: Path = typer.Argument(..., help="Path to the profile YAML to validate"),
) -> None:
    """Validate a traffic profile YAML file."""
    if not profile_path.exists():
        typer.echo(f"Error: file not found: {profile_path}", err=True)
        raise typer.Exit(code=1)

    try:
        from .config import Profile
        Profile.from_yaml(profile_path)
    except Exception as e:
        typer.echo(f"✗ Profile validation failed:\n{e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"✓ Profile is valid: {profile_path}")


@app.command("list-scenarios")
def list_scenarios(
    profile_path: Path = typer.Argument(..., help="Path to the profile YAML"),
) -> None:
    """List scenarios defined in a traffic profile."""
    if not profile_path.exists():
        typer.echo(f"Error: file not found: {profile_path}", err=True)
        raise typer.Exit(code=1)

    try:
        from .config import Profile
        profile = Profile.from_yaml(profile_path)
    except Exception as e:
        typer.echo(f"Error: invalid profile:\n{e}", err=True)
        raise typer.Exit(code=1)

    # Print header
    typer.echo(f"{'ID':<30} {'Weight':<8} {'Surface':<8} {'Via':<20}")
    typer.echo("-" * 70)

    for scenario in profile.scenarios:
        via = scenario.via or "-"
        typer.echo(f"{scenario.id:<30} {scenario.weight:<8.1f} {scenario.surface:<8} {via:<20}")


if __name__ == "__main__":
    app()
