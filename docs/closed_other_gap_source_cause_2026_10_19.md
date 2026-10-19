# Oct 19: diagnose CLOSED:other original gap clock inversions before changing receipts

## Evidence, not a strategy promotion

At 21:18 UTC the authenticated worker #39292750327 (old
`5ed178dd`) still had $9,769.14 equity from $10,000, a
**-$230.86 marked after-cost PAPER loss**. Its original v3 capture
was permanently FAILED after 3,727,350 dropped rows and 5,538
original-adjacent clock regressions. The prior-gap breakdown was
closed:recovered=1,660, **closed:other=1,616**,
closed:recovered_after_rotation_witness=236, and
open:redundant_disconnect=97.

The previous #1389 and #1390 fixes addressed source-witness derived
recovery CLOSE clocks, but cannot establish why a **generic** closed
gap recorded as `other` preceded 1,616 genuine source-time inversions.
That bucket includes unrelated events with INCOMPATIBLE clock
semantics: `out_of_order` records are venue-exchange-time anomaly
markers and cannot be assigned a WS recovery witness's receipt
timestamp; `standby_backfill_overflow` and
`redundant_unseen_retrograde` represent real missing original
coverage and may not be erased to satisfy the source seal.

## Bounded, fail-closed diagnostic

Keep the canonical historical six-bucket gap reason contract
unchanged. For *only* the `closed:other` predecessor of a strict
original-adjacent backwards-clock event, add a fixed eight-item
source-code-only census: out_of_order, standby_backfill_overflow,
redundant_unseen_retrograde, stale, disconnect, handoff, rotation,
and unclassified. Every other arbitrary/unknown gap reason is
unclassified, never surfaced from raw source payloads.

The exact sum must equal the existing `closed:other` adjacent
regression count. Publish both in in-memory original capture negative
telemetry and terminal failure metadata, and render just the top
fixed-vocabulary five counts with a reconciliation flag in the
worker heartbeat. Tests verify four actual reason classes, unknown
private free-text redaction, bool/negative count rejection, and that
an OPEN unknown gap cannot become a CLOSED cause.

**No source timestamps or receipt ordering are changed.** No gap is
suppressed or retimed. Even in a hypothetical future successful
source collection, negative source notices still prohibit claiming
an independently complete 72h source. This change is a prerequisite
to choosing a justified causal next repair rather than applying the
last witnessed-time fix indiscriminately.

## Profit qualification

The fee drag still exceeds observed gross: $240.42 booked fees
against ~$6.18 cumulative realized gross at this mark. The
autonomous profit effort must separately demonstrate *new* positive
absolute after-cost whole-account capital-matched PAPER returns,
with real spread, slippage, funding, maker no-fills and margin,
using a NEW first-received source-complete >=72h cohort.

No ordinary PAPER order/fee/risk/account, active worker or LIVE
permission changes. Old failed archives are never resealed.
