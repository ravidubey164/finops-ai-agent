---
name: cost-health-check
description: Use this when someone asks for a proactive Azure cost health check, spend trend review, waste detection, or tagging-gap analysis without an anomaly alert.
---

# Run a cost health check

Use this skill when no alert exists and a regular review is needed.

## Procedure

1. Confirm the subscription scope, currency, exact UTC date range, granularity, cost type, and data freshness.
2. For every required query, check the local cache first. Reuse a result only when its scope, date window, grouping, filters, cost type, completeness, and freshness satisfy the needed evidence. If no sufficient result exists, query Azure through `scripts/azure_read.py` without waiting for the user to request live data. Fetch only the missing evidence. If a live query is long-running, leave the original process active and wait for its completion rather than launching a duplicate because stdout is silent.
3. Query cost grouped by `ResourceId` for the review window.
4. Rank the top N resources by spend.
5. Compare the current window with an equivalent prior window and identify sustained growth.
6. Before an expensive drill-down, present the ranked candidates as selectable options labelled with aliases and absolute currency deltas, and filter the drill-down to the selection. Users are not expected to know resource IDs or names. If the user declines to choose, proceed with the largest or fastest-growing resources.
7. Drill into `MeterCategory`, `MeterSubCategory`, `Meter`, `ServiceName`, and `ServiceTier` for the largest or fastest-growing resources.
8. Use Resource Graph to check the following waste candidates:
   - unattached disks
   - unassociated public IP addresses
   - stale snapshots
   - stopped but not deallocated virtual machines
   - storage accounts without lifecycle policies
9. Check for resources missing the tags required for cost attribution.
10. Rank findings by estimated or observed currency impact. Label estimates clearly.
11. Report the exact commands or request bodies, evidence, confidence, limitations, and recommended follow-up. If a required live query is blocked, identify the missing conclusion instead of presenting local partial data as complete. Do not make changes to Azure resources.

## Query conventions

Waste detection is especially exposed to truncation: compare `count` against `total_records` on every Resource Graph result, and raise `--max-rows` if the subscription holds more matching resources than the default 10,000-row cap. A truncated listing produces confidently wrong findings.

End cost windows at `...-30T23:59:59Z` / `...-31T23:59:59Z`, or filter on the `BillingMonth` dimension. A window ending at midnight on the first of the next month can leak rows tagged to the following billing month.

State the comparison range alongside the review range, and mark each finding as observed evidence or an inference.

