#!/usr/bin/env python3
"""Read-only Azure Cost Management and Resource Graph command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import az_cli
from cost_collector import cost_query, read_cost_body
from graph_collector import GRAPH_MAX_ROWS, resource_graph
from result_store import (
    DEFAULT_MAX_AGE_MINUTES,
    AzError,
    digest,
    inspect_cache,
    read_json,
    validate_result,
    write_output,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--out",
        type=Path,
        help="Write the result atomically to this path. Nothing is written on failure.",
    )

    subparsers.add_parser("account", parents=[common])
    subparsers.add_parser("subscriptions", parents=[common])
    subparsers.add_parser("roles", parents=[common])

    dimensions = subparsers.add_parser("dimensions", parents=[common])
    dimensions.add_argument("subscription_id", nargs="?")

    graph = subparsers.add_parser("resource-graph", parents=[common])
    graph.add_argument("query")
    graph.add_argument("subscription_id", nargs="?")
    graph.add_argument("--max-rows", type=int, default=GRAPH_MAX_ROWS)

    query = subparsers.add_parser("cost-query", parents=[common])
    query.add_argument("body_file", type=Path)
    query.add_argument("subscription_id", nargs="?")

    cache = subparsers.add_parser(
        "cache", parents=[common], help="Report which cached results are safe to reuse."
    )
    cache.add_argument("--dir", type=Path, default=Path("working/real-output"))
    cache.add_argument("--body-file", type=Path, help="Match the hash of this cost-query body.")
    cache.add_argument("--query", help="Match the hash of this Resource Graph query.")
    cache.add_argument("--max-age-minutes", type=float, default=DEFAULT_MAX_AGE_MINUTES)
    cache.add_argument("--subscription-id", help="Scope to match; cache inspection is offline.")
    cache.add_argument("--details", action="store_true", help="Include rejected filenames and reasons.")
    summary = subparsers.add_parser("summarize", parents=[common], help="Summarize saved costs offline.")
    summary.add_argument("current", type=Path)
    summary.add_argument("--baseline", type=Path)
    summary.add_argument("--group-by", default="ResourceId")
    summary.add_argument("--metric", default="PreTaxCost")
    summary.add_argument("--top", type=int, default=5)
    return parser


def summarize_saved(args: argparse.Namespace) -> Any:
    from cost_summary import summarize

    current = read_json(args.current)
    validate_result(current)
    baseline = read_json(args.baseline) if args.baseline else None
    if args.baseline:
        validate_result(baseline)
    try:
        result = summarize(current, baseline, group_by=args.group_by,
                           metric=args.metric, top=args.top)
    except ValueError as error:
        raise AzError(str(error)) from None
    result["evidence"] = {
        "current": str(args.current),
        "baseline": str(args.baseline) if args.baseline else None,
    }
    return result


def cache_report(args: argparse.Namespace) -> Any:
    if args.body_file and args.query:
        raise AzError("Pass either --body-file or --query, not both.")
    wanted_hash = None
    if args.body_file:
        if not args.body_file.is_file():
            raise AzError(f"Body file not found: {args.body_file}")
        wanted_hash = digest(read_cost_body(args.body_file))
    elif args.query:
        wanted_hash = digest(args.query)
    command = "cost-query" if args.body_file else "resource-graph" if args.query else None
    return inspect_cache(args.dir, wanted_hash, args.max_age_minutes,
                         args.subscription_id, command, args.details)


def dispatch(args: argparse.Namespace) -> Any:
    if args.command == "summarize":
        return summarize_saved(args)
    if args.command == "cache":
        return cache_report(args)
    if args.command == "account":
        return az_cli.account()
    if args.command == "subscriptions":
        return az_cli.subscriptions()
    if args.command == "roles":
        return az_cli.roles()
    if args.command == "dimensions":
        return az_cli.dimensions(args.subscription_id)
    if args.command == "resource-graph":
        if args.max_rows < 1:
            raise AzError("--max-rows must be at least 1.")
        return resource_graph(args.query, args.subscription_id, args.max_rows)

    if not args.body_file.is_file():
        raise AzError(f"Body file not found: {args.body_file}")
    return cost_query(args.body_file, args.subscription_id)


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = dispatch(args)
    except AzError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(error.returncode) from None
    write_output(result, args.out)


if __name__ == "__main__":
    main()
