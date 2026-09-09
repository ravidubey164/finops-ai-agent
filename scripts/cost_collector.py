"""Cost Management query collection: paging, merging, and provenance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import az_cli
from result_store import WRAPPER_VERSION, AzError, digest, utc_now

DEFAULT_COST_TYPE = "AmortizedCost"
MAX_COST_PAGES = 50


def read_cost_body(body_file: Path) -> dict[str, Any]:
    try:
        body = json.loads(body_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AzError(f"Invalid JSON in {body_file}: {error}") from None
    if not isinstance(body, dict):
        raise AzError(f"Cost query body must be a JSON object: {body_file}")
    body.setdefault("type", DEFAULT_COST_TYPE)
    return body


def cost_query(body_file: Path, selected_subscription: str | None) -> dict[str, Any]:
    body = read_cost_body(body_file)
    resolved_subscription = az_cli.subscription_id(selected_subscription)
    current_url = (
        "https://management.azure.com/subscriptions/"
        f"{resolved_subscription}/providers/"
        "Microsoft.CostManagement/query?api-version=2026-06-01"
    )
    pages: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    complete = False
    incomplete_reason: str | None = None

    while current_url:
        if len(pages) >= MAX_COST_PAGES:
            incomplete_reason = f"Stopped at the {MAX_COST_PAGES}-page safety cap."
            break
        if current_url in seen_urls:
            incomplete_reason = "Cost Management returned a repeating nextLink."
            break
        seen_urls.add(current_url)
        if pages:
            az_cli.progress(f"waiting before Cost Management page {len(pages) + 1}")
            az_cli.pace_pages()

        try:
            az_cli.progress(f"requesting Cost Management page {len(pages) + 1}")
            page = az_cli.run_az(
                "rest",
                "--method",
                "post",
                "--url",
                current_url,
                "--body",
                json.dumps(body),
                "--headers",
                "Content-Type=application/json",
                "--output",
                "json",
            )
        except AzError:
            if not pages:
                raise
            incomplete_reason = "A later page failed; earlier pages are preserved."
            break

        if not isinstance(page, dict):
            incomplete_reason = "Cost Management returned an empty response body."
            break

        pages.append(page)
        az_cli.progress(f"received Cost Management page {len(pages)}")
        current_url = page.get("properties", {}).get("nextLink", "")
    else:
        complete = True

    if not pages:
        raise AzError("Cost Management returned no usable pages.")

    result = pages[0]
    properties = result.setdefault("properties", {})
    properties.pop("nextLink", None)
    properties["rows"] = [
        row
        for page in pages
        for row in page.get("properties", {}).get("rows", [])
    ]
    result["wrapper"] = {
        "wrapperVersion": WRAPPER_VERSION,
        "command": "cost-query",
        "fetchedUtc": utc_now(),
        "queryHash": digest(body),
        "queryShapeHash": digest({key: value for key, value in body.items()
                                  if key not in ("timeframe", "timePeriod")}),
        "subscriptionId": resolved_subscription,
        "costType": body.get("type"),
        "granularity": body.get("dataset", {}).get("granularity"),
        "timePeriod": body.get("timePeriod"),
        "pagesFetched": len(pages),
        "rowCount": len(properties["rows"]),
        "complete": complete,
        "incompleteReason": incomplete_reason,
    }
    if not complete:
        print(f"WARNING: partial cost result. {incomplete_reason}", file=sys.stderr)
    else:
        az_cli.progress(f"Cost Management query complete ({len(pages)} page(s))")
    return result
