---
name: investigate-cost-anomaly
description: Use this when an Azure cost anomaly alert or unexpected cost movement needs investigation. Identify the resources driving it and classify the likely cause.
---

# Investigate a cost anomaly

Use this skill when an Azure Cost Management anomaly alert or an unexpected cost movement needs investigation.

## Inputs

- The alert or anomaly date
- Subscription scope
- Anomaly window and comparable baseline window
- Any resource groups named by the alert
- Alternatively, a screenshot may also be provided to illustrate the anomaly and the relevant details.

## Procedure

1. Parse the alert and record the anomaly date, percentage change, named resource groups, and alert scope.
2. Define an anomaly window and a comparable baseline window. State both exact UTC date ranges.
3. For every required query, check the local cache first. Reuse a result only when its scope, date window, grouping, filters, cost type, completeness, and freshness satisfy the needed evidence. If no sufficient result exists, query Azure through `scripts/azure_read.py` without waiting for the user to request live data. Fetch only the missing evidence. If a live query is long-running, leave the original process active and wait for its completion rather than launching a duplicate because stdout is silent.
4. Query `AmortizedCost` for both windows by default, grouped by `ResourceGroupName`. Use `ActualCost` only when the user explicitly requests cash/actual billing analysis.
5. Confirm the alert movement and calculate the absolute currency delta for each group.
6. Before drilling into `ResourceId`, present the ranked resource groups as selectable options labelled with aliases and absolute currency deltas, and filter the drill-down to the selection. Users are not expected to know resource IDs or names. Skip the prompt when one group clearly dominates, and if the user declines to choose, proceed with the top movers by absolute delta.
7. For flagged groups, query both windows grouped by `ResourceId`, using Azure when cached data does not provide both complete windows at the required granularity.
8. Rank resources by absolute currency delta:

   `absolute delta = anomaly-window cost - baseline-window cost`

   Do not rank by percentage change. A small resource can have a large percentage change and still have a small bill impact.
9. For the top movers, query `MeterCategory`, `MeterSubCategory`, `Meter`, `ServiceName`, and `ServiceTier` as needed.
10. Query Resource Graph for resource type, SKU, tags, and creation metadata. Treat tags as sensitive and do not place real values in committed reports.
11. Classify the likely cause:
   - new resource
   - SKU or tier change
   - volume change
   - deletion
   - one-off spike
   - sustained shift
12. Report the evidence, exact commands or request bodies, confidence, and limitations. If a required live query is blocked, identify the missing conclusion instead of presenting local partial data as complete.

## Query conventions

Date windows: Cost Management assigns rows to a billing month, and a window ending at `2026-09-01T00:00:00Z` can leak rows tagged to the next billing month. Either end the window at `...-30T23:59:59Z` / `...-31T23:59:59Z`, or filter on the `BillingMonth` dimension. State the exact convention used in the report.

The verified Cost Management grouping dimensions are:

- `ResourceGroupName`
- `ResourceId`
- `MeterCategory`
- `MeterSubCategory`
- `Meter`
- `ServiceName`
- `ServiceTier`

State whether each conclusion is observed evidence or an inference.

