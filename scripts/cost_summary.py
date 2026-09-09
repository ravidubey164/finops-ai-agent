"""Bounded, aliased summaries of validated Cost Management query results."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from heapq import nlargest


def window(metadata):
    period = metadata.get("timePeriod")
    if not isinstance(period, dict):
        raise ValueError("Summary requires an explicit timePeriod.")
    try:
        start, end = (datetime.fromisoformat(period[key].replace("Z", "+00:00"))
                      for key in ("from", "to"))
        if start.utcoffset() is None or end.utcoffset() is None or end <= start:
            raise ValueError
    except (KeyError, AttributeError, TypeError, ValueError):
        raise ValueError("Summary requires a valid timezone-aware timePeriod.") from None
    return start, end


def context(metadata):
    start, end = window(metadata)
    return {
        "fromUtc": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "toUtc": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fetchedUtc": datetime.fromisoformat(metadata["fetchedUtc"].replace("Z", "+00:00"))
                              .astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "complete": metadata["complete"],
    }


def aggregate(result, group_by, metric):
    columns = [column["name"] for column in result["properties"]["columns"]]
    try:
        group_index, cost_index, currency_index = (columns.index(name)
                                                  for name in (group_by, metric, "Currency"))
    except ValueError:
        raise ValueError("Required grouping, cost metric, or Currency column is missing.") from None
    totals, references = {}, {}
    for row_number, row in enumerate(result["properties"]["rows"]):
        group, currency = row[group_index], row[currency_index]
        if not isinstance(currency, str) or not currency or not (group is None or isinstance(group, str)):
            raise ValueError("Invalid currency or grouping value.")
        try:
            amount = Decimal(str(row[cost_index]))
            if not amount.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            raise ValueError("Cost values must be finite numbers.") from None
        key = (currency, group or "")
        totals[key] = totals.get(key, Decimal(0)) + amount
        references.setdefault(key, row_number)
    return totals, references


def summarize(current, baseline=None, *, group_by="ResourceId", metric="PreTaxCost", top=5):
    if not 1 <= top <= 50:
        raise ValueError("--top must be between 1 and 50.")
    metadata = current["wrapper"]
    for result in (current, baseline) if baseline is not None else (current,):
        info = result["wrapper"]
        if (info.get("command") != "cost-query" or not info.get("queryShapeHash")
                or info.get("costType") not in ("ActualCost", "AmortizedCost")
                or info.get("granularity") not in ("None", "Daily", "Monthly")):
            raise ValueError("Summary requires cost-query provenance with type, granularity, and query shape.")
        window(info)
    if baseline is not None:
        previous = baseline["wrapper"]
        if any(metadata.get(key) != previous.get(key)
               for key in ("subscriptionId", "costType", "granularity", "queryShapeHash")):
            raise ValueError("Comparison scope, cost type, granularity, and query shape must match.")
        start, end = window(metadata)
        prior_start, prior_end = window(previous)
        if max(start, prior_start) < min(end, prior_end):
            raise ValueError("Comparison windows must not overlap.")
    current_totals, current_refs = aggregate(current, group_by, metric)
    baseline_totals, baseline_refs = aggregate(baseline, group_by, metric) if baseline is not None else ({}, {})
    keys = current_totals.keys() | baseline_totals.keys()
    currencies = sorted({currency for currency, group in keys})
    if len(currencies) > 10:
        raise ValueError("Too many currencies for a bounded summary; split the query.")
    groups = []
    for currency in currencies:
        values = [(key, baseline_totals.get(key, Decimal(0)), current_totals.get(key, Decimal(0)))
                  for key in keys if key[0] == currency]
        ranked = nlargest(top, values, key=lambda item: (
            abs(item[2] - item[1]) if baseline is not None else item[2], item[0]))

        def amounts(items):
            before = sum((item[1] for item in items), Decimal(0))
            after = sum((item[2] for item in items), Decimal(0))
            return {"baseline": str(before) if baseline is not None else None,
                    "current": str(after), "delta": str(after - before) if baseline is not None else None}

        selected = {item[0] for item in ranked}
        groups.append({
            "currency": currency, "totals": amounts(values), "itemCount": len(values),
            "increases": str(sum((after - before for key, before, after in values if after > before), Decimal(0))) if baseline is not None else None,
            "decreases": str(sum((after - before for key, before, after in values if after < before), Decimal(0))) if baseline is not None else None,
            "unallocated": amounts([item for item in values if not item[0][1]]),
            "top": [{"alias": "unallocated" if not key[1] else "item-" + sha256((metadata["subscriptionId"] + "|" + group_by + "|" + key[1]).encode()).hexdigest()[:12],
                     **amounts([(key, before, after)]),
                     "currentRow": current_refs.get(key), "baselineRow": baseline_refs.get(key)}
                    for key, before, after in ranked],
            "remaining": {"itemCount": len(values) - len(ranked),
                          **amounts([item for item in values if item[0] not in selected])},
        })
    return {
        "costType": metadata["costType"], "granularity": metadata["granularity"],
        "metric": metric, "groupBy": group_by, "current": context(metadata),
        "baseline": context(baseline["wrapper"]) if baseline is not None else None,
        "equalDuration": (window(metadata)[1] - window(metadata)[0] == window(baseline["wrapper"])[1] - window(baseline["wrapper"])[0]) if baseline is not None else None,
        "currencies": groups,
        "limitations": "Observed costs, not causal attribution or savings. Cost data can lag and be revised. Unequal windows are not normalized. Row references are zero-based first matching rows in properties.rows; unallocated is included in totals, not additional spend.",
    }
