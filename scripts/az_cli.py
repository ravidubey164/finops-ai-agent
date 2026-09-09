"""Azure CLI process boundary: throttle-aware retries and single-call reads."""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import time
from typing import Any

from result_store import AzError

AZ_TIMEOUT_SECONDS = 300
RETRY_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = (45, 90, 180, 300)
PAGE_PACING_SECONDS = 2.0

THROTTLE_MARKERS = (
    "too many requests",
    "throttl",
    "rate limit",
    '"code":"429"',
    "(429)",
)
RETRY_AFTER_PATTERN = re.compile(r"retry[-_ ]?after[\"']?\s*[:=]\s*[\"']?(\d+)", re.IGNORECASE)


def progress(message: str) -> None:
    print(f"azure-read: {message}", file=sys.stderr, flush=True)


def backoff_seconds(attempt: int, error: str) -> float:
    match = RETRY_AFTER_PATTERN.search(error)
    if match:
        return min(int(match.group(1)), 300)
    index = min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)
    return RETRY_BACKOFF_SECONDS[index] * random.uniform(0.8, 1.2)


def pace_pages() -> None:
    time.sleep(PAGE_PACING_SECONDS)


def run_az(*args: str) -> Any:
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        progress(f"starting Azure CLI request (attempt {attempt}/{RETRY_ATTEMPTS})")
        try:
            result = subprocess.run(
                ["az", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=AZ_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            raise AzError("The Azure CLI (az) was not found on PATH.") from None
        except subprocess.TimeoutExpired:
            raise AzError(
                f"az timed out after {AZ_TIMEOUT_SECONDS}s: az {' '.join(args[:2])}"
            ) from None

        if result.returncode == 0:
            if not result.stdout.strip():
                return None
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as error:
                raise AzError(f"az returned output that is not valid JSON: {error}") from None

        error = result.stderr or result.stdout
        throttled = any(marker in error.lower() for marker in THROTTLE_MARKERS)
        if not throttled or attempt == RETRY_ATTEMPTS:
            raise AzError(error, result.returncode)
        delay = backoff_seconds(attempt, error)
        progress(f"request throttled; retrying in {delay:.0f}s")
        time.sleep(delay)

    raise AzError("az retry loop exhausted without a result")


def default_subscription_id() -> str:
    account = run_az("account", "show", "--output", "json")
    subscription_id = account.get("id") if isinstance(account, dict) else None
    if not subscription_id:
        raise AzError("No active Azure subscription was found. Run az login first.")
    return subscription_id


def subscription_id(value: str | None) -> str:
    return value or default_subscription_id()


def account() -> Any:
    return run_az(
        "account",
        "show",
        "--query",
        "{subscription:name,subscriptionId:id,tenantId:tenantId,user:user.name}",
        "--output",
        "json",
    )


def subscriptions() -> Any:
    return run_az(
        "account",
        "list",
        "--query",
        "[].{subscription:name,subscriptionId:id,state:state,isDefault:isDefault}",
        "--output",
        "json",
    )


def roles() -> Any:
    signed_in = run_az("account", "show", "--output", "json")
    assignee = (signed_in or {}).get("user", {}).get("name")
    if not assignee:
        raise AzError("Could not resolve the signed-in identity. Run az login first.")
    return run_az(
        "role",
        "assignment",
        "list",
        "--all",
        "--include-inherited",
        "--include-groups",
        "--assignee",
        assignee,
        "--query",
        "[].{role:roleDefinitionName,scope:scope,principalType:principalType}",
        "--output",
        "json",
    )


def dimensions(selected_subscription: str | None) -> Any:
    return run_az(
        "rest",
        "--method",
        "get",
        "--url",
        "https://management.azure.com/subscriptions/"
        f"{subscription_id(selected_subscription)}/providers/"
        "Microsoft.CostManagement/dimensions?api-version=2025-03-01",
        "--output",
        "json",
    )
