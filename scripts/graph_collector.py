"""Resource Graph collection: skip-token paging, row caps, and provenance."""

from __future__ import annotations

import sys
from typing import Any

import az_cli
from result_store import WRAPPER_VERSION, AzError, digest, utc_now

GRAPH_PAGE_SIZE = 1000
GRAPH_MAX_ROWS = 10000


def resource_graph(
    query: str, selected_subscription: str | None, max_rows: int
) -> dict[str, Any]:
    target = az_cli.subscription_id(selected_subscription)
    rows: list[Any] = []
    total_records: int | None = None
    pages = 0
    complete = True
    incomplete_reason: str | None = None
    skip_token: str | None = None
    seen_tokens: set[str] = set()

    while True:
        page_size = min(GRAPH_PAGE_SIZE, max_rows - len(rows))
        command = [
            "graph",
            "query",
            "--subscriptions",
            target,
            "--graph-query",
            query,
            "--first",
            str(page_size),
        ]
        if skip_token:
            command.extend(["--skip-token", skip_token])
        command.extend(["--output", "json"])
        try:
            page = az_cli.run_az(*command)
        except AzError:
            if not rows:
                raise
            complete = False
            incomplete_reason = "A later page failed; earlier pages are preserved."
            break
        pages += 1
        if not isinstance(page, dict):
            complete = False
            incomplete_reason = "Resource Graph returned an empty response body."
            break

        data = page.get("data") or []
        total_records = page.get("total_records", total_records)
        rows.extend(data)
        next_token = page.get("skip_token") or page.get("skipToken")

        if not next_token:
            break
        if total_records is not None and len(rows) >= total_records:
            break
        if len(rows) >= max_rows:
            complete = False
            incomplete_reason = (
                f"Stopped at the {max_rows}-row cap; raise --max-rows to fetch more."
            )
            break
        if next_token in seen_tokens:
            complete = False
            incomplete_reason = "Resource Graph returned a repeating skip token."
            break
        seen_tokens.add(next_token)
        skip_token = next_token

    if total_records is not None and len(rows) < total_records:
        complete = False
        incomplete_reason = incomplete_reason or (
            f"Returned {len(rows)} of {total_records} matching records."
        )

    if not complete:
        print(f"WARNING: partial Resource Graph result. {incomplete_reason}", file=sys.stderr)

    return {
        "count": len(rows),
        "total_records": total_records,
        "data": rows,
        "wrapper": {
            "wrapperVersion": WRAPPER_VERSION,
            "command": "resource-graph",
            "fetchedUtc": utc_now(),
            "queryHash": digest(query),
            "subscriptionId": target,
            "pagesFetched": pages,
            "maxRows": max_rows,
            "complete": complete,
            "incompleteReason": incomplete_reason,
        },
    }
