#!/usr/bin/env python3
"""Generate comparison report from evaluation results.

Reads a results JSON file produced by runner.py and prints a formatted
comparison table using the rich library.

Usage:
    python report.py results/20250101-120000.json
    python report.py results/latest.json --category efficiency
"""

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text


console = Console()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def load_results(path: str) -> dict:
    """Load results JSON file."""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]File not found: {path}[/red]")
        sys.exit(1)
    return json.loads(p.read_text())


def get_latency(result: dict, agent: str) -> float | None:
    """Extract latency for an agent from a result entry."""
    agent_data = result.get(agent, {})
    if result["type"] == "single_turn":
        return agent_data.get("latency_ms")
    else:
        return agent_data.get("total_latency_ms")


def get_status(result: dict, agent: str) -> str:
    """Extract status for an agent from a result entry."""
    agent_data = result.get(agent, {})
    if result["type"] == "single_turn":
        return agent_data.get("status", "unknown")
    else:
        turns = agent_data.get("turns", [])
        if all(t.get("status") == "ok" for t in turns):
            return "ok"
        statuses = [t.get("status", "?") for t in turns]
        return f"partial ({'/'.join(statuses)})"


def get_response_preview(result: dict, agent: str, max_len: int = 60) -> str:
    """Get a truncated preview of the agent response."""
    agent_data = result.get(agent, {})
    if result["type"] == "single_turn":
        resp = agent_data.get("response", "")
    else:
        turns = agent_data.get("turns", [])
        if turns:
            resp = turns[-1].get("response", "")
        else:
            resp = ""
    if len(resp) > max_len:
        return resp[:max_len] + "..."
    return resp


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------


def print_header(data: dict):
    """Print report header with run metadata."""
    config = data.get("config", {})
    summary = data.get("summary", {})
    ts = data.get("timestamp", "unknown")

    header = Text()
    header.append("Agent Comparison Report\n", style="bold cyan")
    header.append(f"Timestamp: {ts}\n")
    header.append(f"Dataset:   {config.get('dataset', '?')}\n")
    header.append(f"LangGraph: {config.get('langgraph_url', '?')}\n")
    header.append(f"Strands:   {config.get('strands_url', '?')}\n")
    header.append(f"Cases:     {summary.get('total_cases', 0)} total | ")
    header.append(f"LG OK: {summary.get('langgraph_ok', 0)} | ")
    header.append(f"ST OK: {summary.get('strands_ok', 0)}")

    console.print(Panel(header, title="Evaluation Run", border_style="blue"))
    console.print()


def print_per_case_table(results: list, category_filter: str | None = None):
    """Print per-case comparison table."""
    table = Table(title="Per-Case Results", show_lines=True)
    table.add_column("ID", style="cyan", width=22)
    table.add_column("Category", style="magenta", width=14)
    table.add_column("LG Status", width=10)
    table.add_column("ST Status", width=10)
    table.add_column("LG Latency", justify="right", width=10)
    table.add_column("ST Latency", justify="right", width=10)
    table.add_column("Faster", width=8)

    for r in results:
        cat = r.get("category", "unknown")
        if category_filter and cat != category_filter:
            continue

        lg_status = get_status(r, "langgraph")
        st_status = get_status(r, "strands")
        lg_latency = get_latency(r, "langgraph")
        st_latency = get_latency(r, "strands")

        # Determine which is faster
        faster = ""
        if lg_latency and st_latency:
            if lg_latency < st_latency:
                faster = "[green]LG[/green]"
            elif st_latency < lg_latency:
                faster = "[green]ST[/green]"
            else:
                faster = "tie"

        # Color status
        lg_style = "green" if lg_status == "ok" else "red"
        st_style = "green" if st_status == "ok" else "red"

        table.add_row(
            r["id"],
            cat,
            f"[{lg_style}]{lg_status}[/{lg_style}]",
            f"[{st_style}]{st_status}[/{st_style}]",
            f"{lg_latency:.0f}ms" if lg_latency else "-",
            f"{st_latency:.0f}ms" if st_latency else "-",
            faster,
        )

    console.print(table)
    console.print()


def print_category_breakdown(results: list):
    """Print aggregate stats per category."""
    categories: dict[str, list] = {}
    for r in results:
        cat = r.get("category", "unknown")
        categories.setdefault(cat, []).append(r)

    table = Table(title="Category Breakdown", show_lines=True)
    table.add_column("Category", style="magenta", width=16)
    table.add_column("Cases", justify="right", width=6)
    table.add_column("LG OK", justify="right", width=6)
    table.add_column("ST OK", justify="right", width=6)
    table.add_column("LG Avg Latency", justify="right", width=14)
    table.add_column("ST Avg Latency", justify="right", width=14)
    table.add_column("Winner", width=8)

    for cat, cat_results in sorted(categories.items()):
        count = len(cat_results)

        lg_ok = sum(1 for r in cat_results if get_status(r, "langgraph") == "ok")
        st_ok = sum(1 for r in cat_results if get_status(r, "strands") == "ok")

        lg_latencies = [
            get_latency(r, "langgraph")
            for r in cat_results
            if get_latency(r, "langgraph") is not None
        ]
        st_latencies = [
            get_latency(r, "strands")
            for r in cat_results
            if get_latency(r, "strands") is not None
        ]

        lg_avg = sum(lg_latencies) / len(lg_latencies) if lg_latencies else 0
        st_avg = sum(st_latencies) / len(st_latencies) if st_latencies else 0

        winner = ""
        if lg_avg and st_avg:
            if lg_avg < st_avg:
                winner = "[green]LG[/green]"
            elif st_avg < lg_avg:
                winner = "[green]ST[/green]"
            else:
                winner = "tie"

        table.add_row(
            cat,
            str(count),
            str(lg_ok),
            str(st_ok),
            f"{lg_avg:.0f}ms" if lg_avg else "-",
            f"{st_avg:.0f}ms" if st_avg else "-",
            winner,
        )

    console.print(table)
    console.print()


def print_aggregate_summary(results: list):
    """Print overall aggregate comparison."""
    lg_latencies = [
        get_latency(r, "langgraph")
        for r in results
        if get_latency(r, "langgraph") is not None
    ]
    st_latencies = [
        get_latency(r, "strands")
        for r in results
        if get_latency(r, "strands") is not None
    ]

    lg_ok = sum(1 for r in results if get_status(r, "langgraph") == "ok")
    st_ok = sum(1 for r in results if get_status(r, "strands") == "ok")
    total = len(results)

    table = Table(title="Aggregate Summary", show_lines=True)
    table.add_column("Metric", style="bold", width=20)
    table.add_column("LangGraph", justify="right", width=14)
    table.add_column("Strands", justify="right", width=14)

    table.add_row(
        "Success Rate",
        f"{lg_ok}/{total} ({100*lg_ok/total:.0f}%)" if total else "-",
        f"{st_ok}/{total} ({100*st_ok/total:.0f}%)" if total else "-",
    )
    table.add_row(
        "Avg Latency",
        f"{sum(lg_latencies)/len(lg_latencies):.0f}ms" if lg_latencies else "-",
        f"{sum(st_latencies)/len(st_latencies):.0f}ms" if st_latencies else "-",
    )
    table.add_row(
        "Min Latency",
        f"{min(lg_latencies):.0f}ms" if lg_latencies else "-",
        f"{min(st_latencies):.0f}ms" if st_latencies else "-",
    )
    table.add_row(
        "Max Latency",
        f"{max(lg_latencies):.0f}ms" if lg_latencies else "-",
        f"{max(st_latencies):.0f}ms" if st_latencies else "-",
    )
    table.add_row(
        "Error Rate",
        f"{total - lg_ok}/{total}" if total else "-",
        f"{total - st_ok}/{total}" if total else "-",
    )

    console.print(table)
    console.print()


def print_response_comparison(results: list, category_filter: str | None = None):
    """Print side-by-side response previews."""
    table = Table(title="Response Previews", show_lines=True)
    table.add_column("ID", style="cyan", width=22)
    table.add_column("LangGraph Response", width=50)
    table.add_column("Strands Response", width=50)

    for r in results:
        if category_filter and r.get("category") != category_filter:
            continue
        lg_resp = get_response_preview(r, "langgraph", max_len=80)
        st_resp = get_response_preview(r, "strands", max_len=80)
        table.add_row(r["id"], lg_resp, st_resp)

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate comparison report from evaluation results"
    )
    parser.add_argument(
        "results_file",
        help="Path to results JSON file",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Filter by category (efficiency, accuracy, error_recovery, ambiguity, context, safety)",
    )
    parser.add_argument(
        "--responses",
        action="store_true",
        help="Show response previews",
    )
    args = parser.parse_args()

    data = load_results(args.results_file)
    results = data.get("results", [])

    if not results:
        console.print("[red]No results found in file.[/red]")
        sys.exit(1)

    print_header(data)
    print_aggregate_summary(results)
    print_category_breakdown(results)
    print_per_case_table(results, category_filter=args.category)

    if args.responses:
        print_response_comparison(results, category_filter=args.category)


if __name__ == "__main__":
    main()
