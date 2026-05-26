#!/usr/bin/env python3
"""Agent comparison evaluation runner.

Sends the same prompts to both LangGraph and Strands agents,
records responses, latency, and tool usage for comparison.

Usage:
    python runner.py --dataset datasets/comparative.yaml
    python runner.py --dataset datasets/comparative.yaml --langgraph-url http://localhost:8081/invocations
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_LANGGRAPH_URL = os.environ.get(
    "LANGGRAPH_URL", "http://localhost:8081/invocations"
)
DEFAULT_STRANDS_URL = os.environ.get(
    "STRANDS_URL", "http://localhost:8082/invocations"
)
TIMEOUT_SECONDS = 90


# ---------------------------------------------------------------------------
# Agent caller
# ---------------------------------------------------------------------------


async def call_agent(
    client: httpx.AsyncClient,
    url: str,
    prompt: str,
    session_id: str,
) -> dict:
    """Send a prompt to an agent and record response + timing."""
    payload = {"prompt": prompt, "sessionId": session_id}
    start = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, timeout=TIMEOUT_SECONDS)
        latency_ms = (time.perf_counter() - start) * 1000
        resp.raise_for_status()
        body = resp.json()
        return {
            "status": "ok",
            "response": body.get("response", ""),
            "latency_ms": round(latency_ms, 1),
            "raw": body,
        }
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": "timeout",
            "response": "",
            "latency_ms": round(latency_ms, 1),
            "error": f"Timeout after {TIMEOUT_SECONDS}s",
        }
    except httpx.ConnectError as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": "connection_error",
            "response": "",
            "latency_ms": round(latency_ms, 1),
            "error": str(e),
        }
    except httpx.HTTPStatusError as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": "http_error",
            "response": "",
            "latency_ms": round(latency_ms, 1),
            "error": f"{e.response.status_code}: {e.response.text[:200]}",
        }
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": "error",
            "response": "",
            "latency_ms": round(latency_ms, 1),
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Single-turn evaluation
# ---------------------------------------------------------------------------


async def run_single_turn(
    client: httpx.AsyncClient,
    case: dict,
    langgraph_url: str,
    strands_url: str,
) -> dict:
    """Run a single-turn evaluation case against both agents in parallel."""
    prompt = case["prompt"]
    session_id = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"

    langgraph_result, strands_result = await asyncio.gather(
        call_agent(client, langgraph_url, prompt, session_id),
        call_agent(client, strands_url, prompt, session_id),
    )

    return {
        "id": case["id"],
        "category": case.get("category", "unknown"),
        "prompt": prompt,
        "type": "single_turn",
        "metadata": {
            k: v
            for k, v in case.items()
            if k not in ("id", "category", "prompt", "turns")
        },
        "langgraph": langgraph_result,
        "strands": strands_result,
    }


# ---------------------------------------------------------------------------
# Multi-turn evaluation
# ---------------------------------------------------------------------------


async def run_multi_turn(
    client: httpx.AsyncClient,
    case: dict,
    langgraph_url: str,
    strands_url: str,
) -> dict:
    """Run a multi-turn evaluation case, sending turns sequentially."""
    turns = case["turns"]
    session_langgraph = f"eval-{case['id']}-lg-{uuid.uuid4().hex[:8]}"
    session_strands = f"eval-{case['id']}-st-{uuid.uuid4().hex[:8]}"

    langgraph_turns = []
    strands_turns = []

    for turn in turns:
        prompt = turn["prompt"]

        # Send to both agents in parallel for each turn
        lg_result, st_result = await asyncio.gather(
            call_agent(client, langgraph_url, prompt, session_langgraph),
            call_agent(client, strands_url, prompt, session_strands),
        )

        langgraph_turns.append({"prompt": prompt, **lg_result})
        strands_turns.append({"prompt": prompt, **st_result})

    return {
        "id": case["id"],
        "category": case.get("category", "unknown"),
        "type": "multi_turn",
        "turns": [t["prompt"] for t in turns],
        "metadata": {
            k: v
            for k, v in case.items()
            if k not in ("id", "category", "prompt", "turns")
        },
        "langgraph": {
            "session_id": session_langgraph,
            "turns": langgraph_turns,
            "total_latency_ms": round(
                sum(t["latency_ms"] for t in langgraph_turns), 1
            ),
        },
        "strands": {
            "session_id": session_strands,
            "turns": strands_turns,
            "total_latency_ms": round(
                sum(t["latency_ms"] for t in strands_turns), 1
            ),
        },
    }


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def run_evaluation(
    dataset_path: str,
    langgraph_url: str,
    strands_url: str,
) -> dict:
    """Load dataset and run all evaluation cases."""
    with open(dataset_path) as f:
        dataset = yaml.safe_load(f)

    cases = dataset.get("evaluations", [])
    print(f"Loaded {len(cases)} evaluation cases from {dataset_path}")
    print(f"  LangGraph: {langgraph_url}")
    print(f"  Strands:   {strands_url}")
    print()

    results = []
    async with httpx.AsyncClient() as client:
        for i, case in enumerate(cases, 1):
            case_id = case.get("id", f"case_{i}")
            is_multi_turn = "turns" in case

            print(
                f"[{i}/{len(cases)}] {case_id} "
                f"({'multi-turn' if is_multi_turn else 'single-turn'})...",
                end=" ",
                flush=True,
            )

            if is_multi_turn:
                result = await run_multi_turn(
                    client, case, langgraph_url, strands_url
                )
            else:
                result = await run_single_turn(
                    client, case, langgraph_url, strands_url
                )

            results.append(result)

            # Print quick status
            if is_multi_turn:
                lg_status = "ok" if all(
                    t.get("status") == "ok"
                    for t in result["langgraph"]["turns"]
                ) else "error"
                st_status = "ok" if all(
                    t.get("status") == "ok"
                    for t in result["strands"]["turns"]
                ) else "error"
            else:
                lg_status = result["langgraph"]["status"]
                st_status = result["strands"]["status"]

            print(f"LG={lg_status} ST={st_status}")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "dataset": dataset_path,
            "langgraph_url": langgraph_url,
            "strands_url": strands_url,
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "summary": {
            "total_cases": len(results),
            "langgraph_ok": sum(
                1
                for r in results
                if (
                    r.get("langgraph", {}).get("status") == "ok"
                    if r["type"] == "single_turn"
                    else all(
                        t.get("status") == "ok"
                        for t in r.get("langgraph", {}).get("turns", [])
                    )
                )
            ),
            "strands_ok": sum(
                1
                for r in results
                if (
                    r.get("strands", {}).get("status") == "ok"
                    if r["type"] == "single_turn"
                    else all(
                        t.get("status") == "ok"
                        for t in r.get("strands", {}).get("turns", [])
                    )
                )
            ),
        },
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run comparative evaluation of LangGraph vs Strands agents"
    )
    parser.add_argument(
        "--dataset",
        default="datasets/comparative.yaml",
        help="Path to evaluation dataset YAML (default: datasets/comparative.yaml)",
    )
    parser.add_argument(
        "--langgraph-url",
        default=DEFAULT_LANGGRAPH_URL,
        help=f"LangGraph agent URL (default: {DEFAULT_LANGGRAPH_URL})",
    )
    parser.add_argument(
        "--strands-url",
        default=DEFAULT_STRANDS_URL,
        help=f"Strands agent URL (default: {DEFAULT_STRANDS_URL})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: results/<timestamp>.json)",
    )
    args = parser.parse_args()

    # Run evaluation
    output = asyncio.run(
        run_evaluation(args.dataset, args.langgraph_url, args.strands_url)
    )

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = Path("results") / f"{ts}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nResults saved to {out_path}")
    print(
        f"  Total: {output['summary']['total_cases']} cases | "
        f"LangGraph OK: {output['summary']['langgraph_ok']} | "
        f"Strands OK: {output['summary']['strands_ok']}"
    )


if __name__ == "__main__":
    main()
