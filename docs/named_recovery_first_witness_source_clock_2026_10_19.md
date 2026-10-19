# October 19 — first-received named recovery witnesses, not delayed fsync timestamps

## Reproduced causal source defect

Authenticated ongoing PAPER worker #39292750327 at 20:41 UTC still runs
older `5ed178dd`; the original v3 capture has permanently FAILED
(`original_received_clock_regression`), with **3,151,207 original records
dropped**, 4,503 original-adjacent receive-clock inversions and 262,087
records earlier than the PAPER timestamp high water. At that time the
ordinary account had **$9,774.06 marked equity / −$225.94 after fees
and funding** from its $10,000 start, 308 completed trades and 1 new
session close. LIVE remains DISABLED.

An authentic checkpoint/rotation source gap is not closed merely because
time elapsed: an actually received, accepted same-stream WS event is
recorded as its immutable witness and the exact gap `ended_ms` is that
event's first-received timestamp. Previously the *subsequent* asynchronous
gap-close fsync called generic `pump.process(DataGap)`, assigning its
**later wall clock at pump-lock acquisition** as the gap source
observation. A later packet may already have been received and had its
earlier first-received clock captured while the witness's fsync awaited,
producing this false sequence:

```text
first accepted WS witness at 2990
named original gap close at fsync/pump time 3500 (NOT an independent source receipt)
next genuinely first-received WS packet at 3000
=> original source regresses 3500 -> 3000
```

## Narrow fix

For `recovered_after_handoff_witness` and
`recovered_after_rotation_witness` ONLY, construct the original named
gap-close `ReplayRecord` with the **accepted first WS witness
receive time already frozen as the exact immutable `gap.ended_ms`**.
This is a derived *source observation* clock, not a claim that durable
witness write happened at that moment. The source gap's ORIGINAL
start/end and reason remain unchanged, as do original normalized price,
venue exchange timestamp, receive time, and event key. This path is used
for both ordinary named recovery and inherited pending retries, and
for fully acknowledged `allMids` frame completion. The latter remains
serialized inside the mux lock, never between equal-time children.
Generic disconnect, stale, mux aggregate `recovered`, other gap
classes, and all nonwitness source rows retain their old observation
semantics.

The test reproduces an unusually slow witness fsync at 3500 after
witness receipt at 2990 and before processing next original source
packet received at 3000. It proves the original writer sees
2990 -> 2990 -> 3000 without rewriting either market packet,
for BOTH exact named recovery reasons. Malformed, open or generic gap
classes fail closed.

## Critical limits

This only removes a **specific causal latency inversion** from a small
class of *already genuinely accepted* source witnesses. It does NOT
fix the dominating unrelated `closed:other`, mux `recovered`,
cross-source scheduling, or global PAPER receive-clock highwater
inversions. It can still expose true interleaving inversions when
another source is persisted between witness and its close; those
remain negative and cannot be clamped or silently made clean.
Nor does the fix erase actual missing feed windows: closed DATA_GAP
rows remain immutable **negative coverage evidence** for the 72h
qualification.

No existing failed archive may be retrospectively repaired or resealed.
Qualification requires a **NEW**, source-complete >=72h original capture
and two independent funded capital-matched PAPER ledgers strictly
positive after all fees, spread, slippage, funding, misses and realistic
inventory/position capital costs. Trading strategy, fees, risk limits,
open positions, rescue guard and LIVE-disabled mode are unchanged.
