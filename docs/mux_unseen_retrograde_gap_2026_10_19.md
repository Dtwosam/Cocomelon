# October 19 — unseen late standby originals must leave a durable negative gap

## Why source integrity blocks profitability research

The PAPER worker still has negative after-cost equity and strict original
source capture failure; no valid independently clean 72h research archive
currently exists. Reliable original trade prints, books and hourly funding
are prerequisites for capital-matched maker-vs-IOC evaluation.

The redundant WebSocket mux suppresses a late failover candidate whose
exchange time predates its last selected source event. That is fine when
the EXACT original event was already admitted; however a genuinely
previously unseen older print/book was silently discarded with no
source-gap record. Such a disappearance could make an incomplete source
look as if standby backfill was complete.

## Narrow PAPER original-source correction

- For an *unseen* strictly older discarded **standby backfill** candidate, commit a
  `redundant_unseen_retrograde` DataGap with the unchanged exact bounded
  earlier/later original clock values. Never fabricate a price or emit an
  old event into a trading decision.
- Exact already-admitted duplicates remain correctly suppressed with no
  spurious negative gap. Older receive-only live messages on the
  *existing active* lane retain their existing drop/no-gap semantics;
  the negative marker is not an invented disconnect or an assertion that
  every transport reorder denotes a missing source interval.
- Hold the exact missing-source receipt (gap and event key) across sink
  error OR cancellation. Before accepting any later event or gap on that
  stream, retry the same immutable negative receipt; on successful commit
  mark only the rejected event key so its repeat cannot produce an endless
  chain of duplicate gaps.
- Add bounded diagnostic counters for rejected unseen older source rows
  and outstanding uncommitted negative receipts; they cannot grant a
  positive source-completeness certificate.

This preserves the existing mux serialization, source timestamps, venue
data, account book/risk/fees/stop behavior, and LIVE-disabled mode.
The change can only increase evidence of coverage failure when the mux
previously hid it. It does NOT certify a clean source or profitable edge
and does not restart the already-running older PAPER worker.

**Acceptance gate:** full test and research CI green on exact PR commit,
post-merge independent PAPER rescue, actual next-worker first-received
source evidence, and only then genuinely forward full-account cost tests.
