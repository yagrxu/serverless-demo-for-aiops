"""Scheduler — the async dispatch loop.

Drives scenario execution at the configured aggregate RPS using a token bucket
for pacing and a semaphore for bounded concurrency.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .clients import CallContext, Response
from .clients.agent import AgentClient
from .clients.rest import RestClient
from .config import Scenario, ScenarioStep
from .observability import RunEvent, RunManifest, RunSummary, generate_traceparent
from .personas import Persona, PersonaPool
from .sampling import weighted_pick
from .templates import TemplateError, resolve_templates, select_prompt
from .tokenbucket import TokenBucket

logger = logging.getLogger(__name__)


async def dispatch(
    scenario: Scenario,
    persona: Persona,
    rest_client: RestClient,
    agent_client: AgentClient,
    manifest: RunManifest,
    rng: random.Random,
    run_id: str,
) -> None:
    """Dispatch a single scenario for a persona.

    For REST: walk steps in order, resolve templates, call rest_client methods.
    For agent: render prompt, call agent_client, emit one RunEvent.
    On first error in REST scenario, stop and emit error event.
    Never raises — catches all exceptions.
    """
    try:
        traceparent = generate_traceparent()
        ctx = CallContext(
            run_id=run_id,
            scenario_id=scenario.id,
            persona_id=persona.persona_id,
            session_id=persona.session_id,
            traceparent=traceparent,
        )

        if scenario.surface == "rest":
            await _dispatch_rest(scenario, persona, rest_client, manifest, ctx, rng)
        elif scenario.surface == "agent":
            await _dispatch_agent(scenario, persona, agent_client, manifest, ctx, rng)
    except Exception as e:
        # Never let exceptions escape dispatch
        logger.error(f"Unexpected error in dispatch: {e}", exc_info=True)


async def _dispatch_rest(
    scenario: Scenario,
    persona: Persona,
    rest_client: RestClient,
    manifest: RunManifest,
    ctx: CallContext,
    rng: random.Random,
) -> None:
    """Execute REST scenario steps in order."""
    last_result: dict[str, Any] = {}
    steps = scenario.steps or []

    for step in steps:
        try:
            response = await _execute_step(step, persona, rest_client, ctx, last_result, rng)

            # Write event
            ev = RunEvent(
                seq=manifest.seq,
                ts=datetime.now(timezone.utc),
                run_id=ctx.run_id,
                scenario_id=scenario.id,
                persona_id=persona.persona_id,
                surface="rest",
                endpoint=response.endpoint,
                method=response.method,
                status=response.status,
                latency_ms=response.latency_ms,
                error=response.error,
                traceparent=ctx.traceparent,
                session_id=ctx.session_id,
            )
            manifest.write_event(ev)

            # On error, stop the scenario
            if response.error is not None:
                break

            # Pass response to next step
            if response.json and isinstance(response.json, dict):
                last_result = response.json
            else:
                last_result = {}

        except TemplateError as e:
            # Template resolution failed — emit error event and stop
            ev = RunEvent(
                seq=manifest.seq,
                ts=datetime.now(timezone.utc),
                run_id=ctx.run_id,
                scenario_id=scenario.id,
                persona_id=persona.persona_id,
                surface="rest",
                endpoint=f"template_error:{step.call}",
                method=None,
                status=None,
                latency_ms=0.0,
                error=f"template_error: {e}",
                traceparent=ctx.traceparent,
                session_id=ctx.session_id,
            )
            manifest.write_event(ev)
            break
        except Exception as e:
            ev = RunEvent(
                seq=manifest.seq,
                ts=datetime.now(timezone.utc),
                run_id=ctx.run_id,
                scenario_id=scenario.id,
                persona_id=persona.persona_id,
                surface="rest",
                endpoint=f"error:{step.call}",
                method=None,
                status=None,
                latency_ms=0.0,
                error=str(e),
                traceparent=ctx.traceparent,
                session_id=ctx.session_id,
            )
            manifest.write_event(ev)
            break


async def _execute_step(
    step: ScenarioStep,
    persona: Persona,
    rest_client: RestClient,
    ctx: CallContext,
    last_result: dict[str, Any],
    rng: random.Random,
) -> Response:
    """Execute a single REST step by calling the appropriate client method."""
    # Resolve path_params
    path_params = resolve_templates(step.path_params, persona, last_result, rng) or {}
    # Resolve body
    body = resolve_templates(step.body, persona, last_result, rng) or {}

    call_name = step.call

    if call_name == "list_cats":
        return await rest_client.list_cats(ctx)
    elif call_name == "get_cat":
        cat_id = path_params.get("cat_id", "")
        return await rest_client.get_cat(ctx, cat_id=cat_id)
    elif call_name == "create_cat":
        return await rest_client.create_cat(ctx, body=body)
    elif call_name == "list_feedings":
        cat_id = path_params.get("cat_id", "")
        return await rest_client.list_feedings(ctx, cat_id=cat_id)
    elif call_name == "create_feeding":
        return await rest_client.create_feeding(ctx, body=body)
    elif call_name == "get_health":
        cat_id = path_params.get("cat_id", "")
        return await rest_client.get_health(ctx, cat_id=cat_id)
    elif call_name == "get_alerts":
        cat_id = path_params.get("cat_id", "")
        return await rest_client.get_alerts(ctx, cat_id=cat_id)
    elif call_name == "post_telemetry":
        device_id = path_params.get("id", path_params.get("device_id", ""))
        return await rest_client.post_telemetry(ctx, device_id=device_id, body=body)
    elif call_name == "post_command":
        device_id = path_params.get("id", path_params.get("device_id", ""))
        return await rest_client.post_command(ctx, device_id=device_id, body=body)
    else:
        return Response(error=f"unknown_call:{call_name}", endpoint=f"unknown:{call_name}", method="?")


async def _dispatch_agent(
    scenario: Scenario,
    persona: Persona,
    agent_client: AgentClient,
    manifest: RunManifest,
    ctx: CallContext,
    rng: random.Random,
) -> None:
    """Execute an agent scenario — render prompt and dispatch."""
    prompts = scenario.prompts or []
    prompt = select_prompt(prompts, persona, rng)

    via = scenario.via or "chatbot"

    if via == "chatbot":
        response = await agent_client.chat_via_bff(ctx, prompt)
    elif via == "langgraph_direct":
        response = await agent_client.invoke_langgraph(ctx, prompt)
    elif via == "strands_direct":
        response = await agent_client.invoke_strands(ctx, prompt)
    else:
        response = Response(error=f"unknown_via:{via}", endpoint=f"agent:{via}", method="POST")

    ev = RunEvent(
        seq=manifest.seq,
        ts=datetime.now(timezone.utc),
        run_id=ctx.run_id,
        scenario_id=scenario.id,
        persona_id=persona.persona_id,
        surface="agent",
        endpoint=response.endpoint,
        method="POST",
        status=response.status,
        latency_ms=response.latency_ms,
        error=response.error,
        traceparent=ctx.traceparent,
        session_id=ctx.session_id,
    )
    manifest.write_event(ev)


class Scheduler:
    """Main scheduler loop — paces scenario dispatch at the configured RPS."""

    def __init__(
        self,
        scenarios: list[Scenario],
        persona_pool: PersonaPool,
        rps: float,
        duration: timedelta | None,
        rng: random.Random,
        manifest: RunManifest,
        rest_client: RestClient,
        agent_client: AgentClient,
        dry_run: bool = False,
    ) -> None:
        self._scenarios = scenarios
        self._persona_pool = persona_pool
        self._rps = rps
        self._duration = duration
        self._rng = rng
        self._manifest = manifest
        self._rest_client = rest_client
        self._agent_client = agent_client
        self._dry_run = dry_run

        # Pacing
        capacity = max(1, int(rps * 2))
        self._bucket = TokenBucket(rate=rps, capacity=capacity)

        # Bounded concurrency
        concurrency = max(4, int(rps * 4))
        self._semaphore = asyncio.Semaphore(concurrency)

        self._shutdown = False
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> RunSummary:
        """Main loop: pace, pick, dispatch until deadline or shutdown."""
        deadline = None
        if self._duration is not None:
            deadline = time.monotonic() + self._duration.total_seconds()

        try:
            while not self._shutdown:
                # Check deadline
                if deadline is not None and time.monotonic() >= deadline:
                    break

                # Pacing
                await self._bucket.acquire(1)

                # Check deadline again after waiting
                if deadline is not None and time.monotonic() >= deadline:
                    break

                # Try to acquire concurrency slot
                acquired = self._semaphore._value > 0  # noqa: SLF001
                if not acquired:
                    # Saturation — emit event and continue
                    ev = RunEvent(
                        seq=self._manifest.seq,
                        ts=datetime.now(timezone.utc),
                        run_id=self._manifest.run_id,
                        scenario_id="__saturation__",
                        persona_id="__system__",
                        surface="rest",
                        endpoint="saturation_drop",
                        latency_ms=0.0,
                        traceparent=generate_traceparent(),
                        saturation_drop=True,
                    )
                    self._manifest.write_event(ev)
                    continue

                await self._semaphore.acquire()

                # Pick scenario and persona
                scenario = weighted_pick(
                    self._scenarios, by=lambda s: s.weight, rng=self._rng
                )
                persona = self._persona_pool.pick(scenario)

                if self._dry_run:
                    # In dry-run mode, just emit a placeholder event without HTTP calls
                    ev = RunEvent(
                        seq=self._manifest.seq,
                        ts=datetime.now(timezone.utc),
                        run_id=self._manifest.run_id,
                        scenario_id=scenario.id,
                        persona_id=persona.persona_id,
                        surface=scenario.surface,
                        endpoint=f"dry_run:{scenario.id}",
                        latency_ms=0.0,
                        traceparent=generate_traceparent(),
                        session_id=persona.session_id,
                    )
                    self._manifest.write_event(ev)
                    self._semaphore.release()
                    continue

                # Spawn dispatch task
                task = asyncio.create_task(
                    self._dispatch_and_release(scenario, persona)
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        except asyncio.CancelledError:
            pass

        # Drain in-flight tasks
        await self._drain()

        # Close manifest and return summary
        self._manifest.close()
        return self._manifest.summary()

    async def _dispatch_and_release(
        self, scenario: Scenario, persona: Persona
    ) -> None:
        """Dispatch and release the semaphore when done."""
        try:
            await dispatch(
                scenario=scenario,
                persona=persona,
                rest_client=self._rest_client,
                agent_client=self._agent_client,
                manifest=self._manifest,
                rng=self._rng,
                run_id=self._manifest.run_id,
            )
        finally:
            self._semaphore.release()

    async def _drain(self, timeout: float = 30.0) -> None:
        """Wait for in-flight tasks to complete."""
        if self._tasks:
            done, pending = await asyncio.wait(
                self._tasks, timeout=timeout
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=5.0)

    def shutdown(self) -> None:
        """Signal the scheduler to stop."""
        self._shutdown = True
