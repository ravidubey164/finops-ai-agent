# Agent safety rules

## Azure access

- This repository is for investigation only. Never create, modify, scale, restart, or delete an
  Azure resource.
- Use `.venv/bin/python scripts/azure_read.py` for all Azure access. It is a read-only wrapper.
- The wrapper is a behavioural guardrail, not an enforcement boundary. The signed-in identity has
  broader Azure permissions, so never run `az` outside the wrapper.
- A `PreToolUse` hook (`.github/hooks/block-azure-writes.json`) denies unapproved `az` commands at
  runtime. Treat a denial as a correct stop, not an obstacle to work around. It depends on VS Code
  preview features being enabled, so never assume it is active; these instructions remain the
  primary control.
- Never ask the user to grant broader permissions or approve a destructive command.

## Querying

- Use `subscriptions` to discover visible subscriptions. Cost, Resource Graph, and dimensions
  queries accept a positional subscription ID; local cache checks require `--subscription-id`.
- Before querying, run `cache` and reuse only results it lists under `reusable`:

  ```bash
  ./.venv/bin/python scripts/azure_read.py cache --body-file <query.json> --subscription-id <id>
  ```

  It validates saved data and embedded provenance, including subscription, query, completeness,
  and age. Use `--details` only when rejection reasons are needed; legacy manifests are ignored.
- Treat this as cache-first, not cache-only. Determine the evidence needed for the user's question
  before selecting cached results. Reuse matching, complete, sufficiently fresh results, but fetch
  missing or analytically insufficient evidence directly from Azure through the approved wrapper.
  Do not require the user to request live querying or provide Azure commands, and do not silently
  narrow the question to fit the available local data.
- Check each required query independently. A reusable result at one grouping level, for one date
  window, or for one drill-down does not satisfy a missing baseline, dimension, resource metadata,
  or other required evidence. Preserve useful cached results and fetch only what is missing.
- If Azure collection is blocked by authentication, permissions, exhausted retries, or a safety
  denial, report the blocker and the unanswered part of the question. Never present partial local
  evidence as a completed investigation.
- Do not interpret silent stdout as a failed query. The wrapper emits progress on stderr, and a
  result file is written only after the command returns. Never launch a duplicate live query while
  the original process is still running. For a long-running query, leave the original process
  running, tell the user it is in progress, and continue only when that process completes; then
  inspect its exit status and `wrapper.complete` before starting the next query.
- Save every result with `--out <path>`, never a shell redirect. A failed redirect leaves a
  zero-byte file that a later run could mistake for valid data.
- Check `wrapper.complete` on every result before using it. If it is `false`, treat the data as
  partial and say so in the report.
- Start analysis with `summarize <current.json> --baseline <baseline.json> --group-by <dimension>`.
  Omit `--baseline` for top spend. Read raw rows locally only for flagged-item drill-down; do not
  dump inventories into chat. Summary row references are zero-based and aliases remain stable.
- Cost queries default to `AmortizedCost`; set `"type": "ActualCost"` explicitly for actual cash
  cost analysis. Always report which cost type was used.
- Cost Management throttles hard. After retries fail, historical evidence may exceed the cache
  age limit, but scope/query/structure/completeness checks must still pass. Disclose staleness.
- The Query API is not designed for repeated or long-range historical pulls. For recurring
  analysis or multi-month history, prefer Cost Management scheduled exports (or Cost Details)
  to storage and analyse the exported data locally. Use live queries for targeted investigation
  windows and drill-downs. Note that exports must already exist; creating one is a write
  operation and is out of scope for this repository.
- Prefer one broad query over several narrow ones. Group by the levels needed in a single call,
  omit granularity unless the trend shape is required, and filter drill-downs to the scopes
  already flagged. Never run cost queries in parallel; the limit is per scope.
- Do not use `jq`; it is not installed in the supported WSL environment. Use Python instead.

## Data handling

- Commit configuration, documentation, scripts, tests, and sanitised examples. Real investigation
  data belongs under `working/`, which is gitignored.
- Never put real subscription IDs, tenant IDs, full resource IDs, tags, account identities, or raw
  cost exports in a committed file or a user-facing response. Use stable aliases.
- Every cost figure must state its currency, exact date range, granularity, and whether it is
  actual or amortised, plus the cost-data freshness caveat.
- Rank findings by absolute currency delta, not percentage change.
- Report the evidence, the exact command or query, confidence, and limitations.
