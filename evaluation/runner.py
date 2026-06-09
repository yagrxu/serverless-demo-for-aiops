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
import sys
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
    model_id: str | None = None,
) -> dict:
    """Send a prompt to an agent and record response + timing."""
    payload = {"prompt": prompt, "sessionId": session_id}
    if model_id:
        payload["model_id"] = model_id
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


async def run_model_comparison(
    dataset_path: str,
    langgraph_url: str,
    strands_url: str,
    models: list[str],
) -> dict:
    """Run evaluation across multiple models for comparison."""
    with open(dataset_path) as f:
        dataset = yaml.safe_load(f)

    cases = dataset.get("evaluations", [])
    print(f"Loaded {len(cases)} evaluation cases from {dataset_path}")
    print(f"  Models: {', '.join(models)}")
    print(f"  LangGraph: {langgraph_url}")
    print(f"  Strands:   {strands_url}")
    print()

    model_results = {}
    for model_id in models:
        short_name = model_id.split(":")[0].split(".")[-1]
        print(f"\n{'='*60}")
        print(f"  Model: {short_name} ({model_id})")
        print(f"{'='*60}\n")

        results = []
        async with httpx.AsyncClient() as client:
            for i, case in enumerate(cases, 1):
                case_id = case.get("id", f"case_{i}")
                is_multi_turn = "turns" in case

                print(
                    f"  [{i}/{len(cases)}] {case_id}...",
                    end=" ",
                    flush=True,
                )

                if is_multi_turn:
                    session_id = f"eval-{case_id}-{uuid.uuid4().hex[:8]}"
                    turns_results = {"langgraph": [], "strands": []}
                    for turn in case["turns"]:
                        lg_r, st_r = await asyncio.gather(
                            call_agent(client, langgraph_url, turn["prompt"], session_id, model_id),
                            call_agent(client, strands_url, turn["prompt"], session_id, model_id),
                        )
                        turns_results["langgraph"].append({"prompt": turn["prompt"], **lg_r})
                        turns_results["strands"].append({"prompt": turn["prompt"], **st_r})
                    results.append({
                        "id": case_id,
                        "category": case.get("category", "unknown"),
                        "type": "multi_turn",
                        "langgraph": turns_results["langgraph"],
                        "strands": turns_results["strands"],
                    })
                    print("done")
                else:
                    session_id = f"eval-{case_id}-{uuid.uuid4().hex[:8]}"
                    lg_r, st_r = await asyncio.gather(
                        call_agent(client, langgraph_url, case["prompt"], session_id, model_id),
                        call_agent(client, strands_url, case["prompt"], session_id, model_id),
                    )
                    results.append({
                        "id": case_id,
                        "category": case.get("category", "unknown"),
                        "type": "single_turn",
                        "prompt": case["prompt"],
                        "langgraph": lg_r,
                        "strands": st_r,
                    })
                    print(f"LG={lg_r['status']} ST={st_r['status']}")

        model_results[model_id] = results

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "model_comparison",
        "config": {
            "dataset": dataset_path,
            "models": models,
            "langgraph_url": langgraph_url,
            "strands_url": strands_url,
        },
        "model_results": model_results,
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
        "--models",
        nargs="+",
        default=None,
        help="Model IDs to compare (sends model_id in payload for dynamic switching)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: results/<timestamp>.json)",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run LLM-as-judge after collecting responses",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Judge pass threshold (default: 0.7, only used with --judge)",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Bedrock model ID for the judge (default: env JUDGE_MODEL_ID or haiku)",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with code 1 if judge score is below threshold",
    )
    args = parser.parse_args()

    # Run evaluation
    if args.models:
        output = asyncio.run(
            run_model_comparison(args.dataset, args.langgraph_url, args.strands_url, args.models)
        )
    else:
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

    # Run LLM-as-judge if requested
    if args.judge:
        print("\n" + "=" * 60)
        print("Running LLM-as-judge...")
        print("=" * 60 + "\n")

        from judge import run_judge

        judge_model = args.judge_model or os.environ.get(
            "JUDGE_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        judge_output = run_judge(str(out_path), judge_model, args.threshold)

        # Save judge results
        judge_path = out_path.with_name(f"{out_path.stem}-judged.json")
        judge_path.write_text(json.dumps(judge_output, ensure_ascii=False, indent=2))

        # Print combined report
        _print_combined_report(output, judge_output)

        if args.fail_on_regression and not judge_output["summary"]["overall_pass"]:
            sys.exit(1)


# ---------------------------------------------------------------------------
# Combined report
# ---------------------------------------------------------------------------


def _print_combined_report(eval_output: dict, judge_output: dict):
    """Print a combined report merging responses and judge scores."""
    results = eval_output.get("results", [])
    judgments = {j["id"]: j for j in judge_output.get("judgments", [])}
    summary = judge_output["summary"]

    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║              AGENT EVALUATION REPORT                            ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Judge Model:      {summary['model_id']}")
    print(f"  Per-case threshold: {summary['threshold']}")
    print(f"  Average threshold:  {summary['avg_threshold']}")
    print(f"  Total cases:      {summary['total_cases']}")
    print()

    # Per-case details
    print("┌─────────────────────────────────────────────────────────────────┐")
    print("│  PER-CASE RESULTS                                              │")
    print("└─────────────────────────────────────────────────────────────────┘")

    for r in results:
        case_id = r["id"]
        category = r.get("category", "?")
        j = judgments.get(case_id, {})

        lg_score = j.get("langgraph", {}).get("score", -1)
        st_score = j.get("strands", {}).get("score", -1)
        lg_reasoning = j.get("langgraph", {}).get("reasoning", "")
        st_reasoning = j.get("strands", {}).get("reasoning", "")

        lg_icon = "✅" if lg_score >= summary["threshold"] else "❌"
        st_icon = "✅" if st_score >= summary["threshold"] else "❌"

        print()
        print(f"  ── {case_id} [{category}] ──")

        # Show prompt
        if r["type"] == "single_turn":
            prompt_preview = r.get("prompt", "")[:80]
            print(f"  Prompt: {prompt_preview}")
        else:
            turns = r.get("turns", [])
            print(f"  Turns:  {' → '.join(t[:30] for t in turns)}")

        print()

        # LangGraph
        print(f"  LangGraph {lg_icon} {lg_score:.2f}")
        if r["type"] == "single_turn":
            resp = r.get("langgraph", {}).get("response", "")
            latency = r.get("langgraph", {}).get("latency_ms", 0)
        else:
            turns_data = r.get("langgraph", {}).get("turns", [])
            resp = turns_data[-1].get("response", "") if turns_data else ""
            latency = r.get("langgraph", {}).get("total_latency_ms", 0)
        print(f"    Latency: {latency:.0f}ms")
        print(f"    Response: {resp[:120]}{'...' if len(resp) > 120 else ''}")
        print(f"    Judge: {lg_reasoning}")

        print()

        # Strands
        print(f"  Strands  {st_icon} {st_score:.2f}")
        if r["type"] == "single_turn":
            resp = r.get("strands", {}).get("response", "")
            latency = r.get("strands", {}).get("latency_ms", 0)
        else:
            turns_data = r.get("strands", {}).get("turns", [])
            resp = turns_data[-1].get("response", "") if turns_data else ""
            latency = r.get("strands", {}).get("total_latency_ms", 0)
        print(f"    Latency: {latency:.0f}ms")
        print(f"    Response: {resp[:120]}{'...' if len(resp) > 120 else ''}")
        print(f"    Judge: {st_reasoning}")

    # Aggregate summary
    print()
    print("┌─────────────────────────────────────────────────────────────────┐")
    print("│  SUMMARY                                                        │")
    print("└─────────────────────────────────────────────────────────────────┘")
    print()
    print(f"  {'Agent':<12} {'Avg':>6} {'Min':>6} {'Below 0.7':>10} {'Result':>8}")
    print(f"  {'─'*12} {'─'*6} {'─'*6} {'─'*10} {'─'*8}")
    print(
        f"  {'LangGraph':<12} "
        f"{summary['langgraph']['avg_score']:>5.3f} "
        f"{summary['langgraph']['min_score']:>5.3f} "
        f"{summary['langgraph']['cases_below_threshold']:>10} "
        f"{'PASS ✅' if summary['langgraph']['pass'] else 'FAIL ❌':>8}"
    )
    print(
        f"  {'Strands':<12} "
        f"{summary['strands']['avg_score']:>5.3f} "
        f"{summary['strands']['min_score']:>5.3f} "
        f"{summary['strands']['cases_below_threshold']:>10} "
        f"{'PASS ✅' if summary['strands']['pass'] else 'FAIL ❌':>8}"
    )
    print()
    print(f"  Overall: {'PASS ✅' if summary['overall_pass'] else 'FAIL ❌'}")
    print(f"  (fail if any case < {summary['threshold']} OR avg < {summary['avg_threshold']})")
    print()


if __name__ == "__main__":
    main()
