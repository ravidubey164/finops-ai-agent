"""Atomic result storage, provenance validation, and offline cache inspection."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WRAPPER_VERSION = 3
DEFAULT_MAX_AGE_MINUTES = 15


class AzError(RuntimeError):
    def __init__(self, message: str, returncode: int = 1) -> None:
        super().__init__(message.strip() or "az command failed")
        self.returncode = returncode


def write_output(payload: Any, out_path: Path | None) -> None:
    text = json.dumps(payload, indent=2)
    if out_path is None:
        print(text)
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(out_path, text)
    print(f"Wrote {out_path}", file=sys.stderr)


def write_atomic(path: Path, text: str) -> None:
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest(value: Any) -> str:
    canonical = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":"))
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def age_minutes(fetched_utc: str | None) -> float | None:
    try:
        fetched = datetime.fromisoformat(fetched_utc.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - fetched).total_seconds() / 60
    except (AttributeError, TypeError, ValueError):
        return None


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise AzError("Unreadable or invalid JSON file.") from None


def validate_result(result: Any) -> dict[str, Any]:
    metadata = result.get("wrapper") if isinstance(result, dict) else None
    if not isinstance(metadata, dict) or metadata.get("wrapperVersion") != WRAPPER_VERSION:
        raise AzError("Missing or outdated provenance.")
    if metadata.get("complete") is not True:
        raise AzError("Incomplete result.")
    age = age_minutes(metadata.get("fetchedUtc"))
    if age is None or age < 0:
        raise AzError("Invalid or future fetch timestamp.")
    if not all(isinstance(metadata.get(key), str) and metadata[key]
               for key in ("subscriptionId", "queryHash")):
        raise AzError("Missing scope or query hash.")
    if metadata.get("command") == "cost-query":
        properties = result.get("properties")
        if not isinstance(properties, dict):
            raise AzError("Missing cost properties.")
        columns, rows = properties.get("columns"), properties.get("rows")
        if (not isinstance(columns, list) or not columns
                or not all(isinstance(column, dict) and isinstance(column.get("name"), str)
                           for column in columns)
                or len({column["name"] for column in columns}) != len(columns)
                or not isinstance(rows, list)
                or not all(isinstance(row, list) and len(row) == len(columns) for row in rows)
                or metadata.get("rowCount") != len(rows) or properties.get("nextLink")):
            raise AzError("Malformed or truncated cost rows.")
    elif metadata.get("command") == "resource-graph":
        rows = result.get("data")
        if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
                or result.get("count") != len(rows) or result.get("total_records") != len(rows)
                or result.get("skip_token") or result.get("skipToken")):
            raise AzError("Malformed or truncated Resource Graph rows.")
    else:
        raise AzError("Unsupported result command.")
    return metadata


def inspect_cache(directory: Path, wanted_hash: str | None, max_age: float,
                  selected_subscription: str | None = None, command: str | None = None,
                  details: bool = False) -> dict[str, Any]:
    if not math.isfinite(max_age) or max_age < 0:
        raise AzError("--max-age-minutes must be finite and non-negative.")
    reusable, rejected = [], []
    for path in sorted(directory.glob("*.json")):
        if path.name == "manifest.json":
            continue
        try:
            metadata = validate_result(read_json(path))
            if not wanted_hash or not selected_subscription or not command:
                raise AzError("Specify a query and --subscription-id for reuse.")
            if metadata["subscriptionId"].lower() != selected_subscription.lower():
                raise AzError("Subscription does not match.")
            if metadata["command"] != command or metadata["queryHash"] != wanted_hash:
                raise AzError("Query does not match.")
            if age_minutes(metadata["fetchedUtc"]) > max_age:
                raise AzError("Result exceeds the age limit.")
            reusable.append(path.name)
        except AzError as error:
            rejected.append({"file": path.name, "reason": str(error)})
    report = {"reusable": reusable, "rejectedCount": len(rejected)}
    if details:
        report["rejected"] = rejected
    return report
