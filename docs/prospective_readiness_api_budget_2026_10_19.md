# October 19 — reduce failed trade-quality readiness API fanout

## Observed blockage

Current PAPER remains negative after paid fees and funding, while the strict
original market source is failed. The independent prediction/comparison
readiness workflow cannot promote anything from that source; it must
nevertheless report genuine, signed, prospectively frozen research controls
and their failures to avoid repeating bad trading candidates.

At 17:39–17:40 UTC, multiple independent scheduled GitHub jobs failed
with `HTTP 403: API rate limit exceeded for installation`, rather than
a candidate-model profitability verdict. The readiness resolver scanned
up to **40 successful historical artifacts from each of two** ledger
workflows and each candidate required an artifact API request and a ZIP
download. Across concurrently scheduled scripts this fanout needlessly
exhausts shared credentials. It also re-queried the newest artifact.

## Contained, fail-closed fix

- Restrict each candidate search to **12 most recent completed upstream
  runs** from a first page of 20; no continued scan for an older profitable
  study. The MOST RECENT run must still be successful with exactly one
  intact, SHA256-verified artifact. If the recent window cannot form an
  exact matching signed cohort, readiness is BLOCKED.
- Deduplicate the repeated latest-run artifact API call with a per-job
  cache keyed by exact run ID and expected artifact prefix. Cache missing
  results as **missing**, never as valid fallback.
- Lower the per-run artifact metadata request from 100 to 20, without
  changing artifact SHA256 validation or matching immutable prospective
  start and frozen training digest.
- Do NOT use a cached value across jobs/runs or infer a missing artifact's
  contents. The reduced lookback is a transparent research-eligibility
  constraint, not evidence of profit or an instruction to live trade.
- Keep original PAPER account, subscriptions, risk, fees, funding, active
  positions, all failed historical model verdicts, and LIVE-disabled
  execution unchanged.

This reduces the resolver's maximum artifact scans per candidate family
from 40 to 12 (**70% reduction**) without certifying future GitHub API
availability. A still-exhausted installation budget remains an explicit
failure, never a green candidate gate.

**Financial acceptance:** A NEW independently clean forward cohort must
achieve positive absolute marked whole-account returns *after real fees,
funding, spread/slippage and missed fills* in both baseline and challenger
before any promotion. No profitable edge has been verified.
