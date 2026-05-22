"""Traffic generator for the cat-care AIOps demo."""
from __future__ import annotations

import io
import random
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Literal

from .config import Profile  # noqa: F401
from .observability import RunSummary


async def run_once(
    target: Literal["local", "cloud"],
    profile_path: Path | str,
    rps: float = 1.0,
    duration_s: float = 300.0,
    seed: int | None = None,
    out_dir: Path | str = Path("./runs"),
    dry_run: bool = False,
) -> RunSummary:
    """Main entrypoint: run the traffic generator once.

    Args:
        target: "local" or "cloud"
        profile_path: Path to the profile YAML file
        rps: Requests per second
        duration_s: Duration in seconds
        seed: RNG seed (None = random)
        out_dir: Output directory for manifest files
        dry_run: If True, pick scenarios without making HTTP calls

    Returns:
        RunSummary with counts and latency stats.
    """
    from .clients.agent import AgentClient
    from .clients.rest import RestClient
    from .observability import RunManifest
    from .personas import PersonaPool
    from .scheduler import Scheduler
    from .targets import resolve_endpoints

    # Resolve endpoints
    endpoints = resolve_endpoints(target)

    # Load and validate profile
    profile = Profile.from_yaml(Path(profile_path))

    # Set up RNG
    run_id = uuid.uuid4().hex
    if seed is None:
        seed = hash(run_id) & 0xFFFFFFFF
    rng = random.Random(seed)

    # Build persona pool
    persona_pool = PersonaPool(profile.personas, seed)

    # Build clients
    rest_client = RestClient(base_url=endpoints.api_base_url, auth=endpoints.auth)
    agent_client = AgentClient(
        chatbot_url=endpoints.chatbot_url,
        langgraph_url=endpoints.langgraph_url,
        strands_url=endpoints.strands_url,
    )

    # Create output directory and manifest
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    manifest_path = out_path / f"{run_id}.jsonl"

    if dry_run:
        sink = io.StringIO()
    else:
        sink = open(manifest_path, "w")  # noqa: SIM115

    try:
        manifest = RunManifest(run_id=run_id, sink=sink)

        # Build and run scheduler
        duration = timedelta(seconds=duration_s)
        scheduler = Scheduler(
            scenarios=profile.scenarios,
            persona_pool=persona_pool,
            rps=rps,
            duration=duration,
            rng=rng,
            manifest=manifest,
            rest_client=rest_client,
            agent_client=agent_client,
            dry_run=dry_run,
        )

        summary = await scheduler.run()

        # Upload to S3 for cloud runs if bucket is configured
        import os
        s3_bucket = os.environ.get("TRAFGEN_S3_BUCKET")
        if target == "cloud" and s3_bucket and not dry_run:
            manifest.upload_to_s3(s3_bucket, f"{run_id}.jsonl")

        return summary
    finally:
        if not dry_run and hasattr(sink, "close"):
            sink.close()
        await rest_client.close()
        await agent_client.close()
