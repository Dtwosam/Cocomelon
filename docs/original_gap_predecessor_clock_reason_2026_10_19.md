# October 19 — classify the real gap receipt that precedes raw-clock reversals

## Actual source and after-cost account

Authenticated ordinary PAPER worker #39255842615 at 2026-10-19
13:20:44 UTC, on #1372 atomic-allMids merge `6c9f045a`,
had **$9,772.15 marked equity / -$227.85 net** versus the
$10,000 start, **304 closed PAPER trades, two open positions**,
booked trading fees **$236.94**, gross realized **+$18.78**,
and funding **-$2.92**. LIVE remains OFF.

Its NEW original mainnet v3 capture is permanently **FAILED**:
282,144 observations offered, only 11,368 durably written,
**270,776 dropped**, 17,278 receive-clock regressions. The first
raw-clock regression is associated with a `trade` following an
original `data_gap` record. The maximum backward jump so far is
123,072ms; there are 533 adjacent-original clock reversals versus
17,278 records below PAPER's clock highwater. The allMids sibling
interleave fix was adopted, but cannot qualify this run.

## What is still missing

`data_gap -> other` identifies a source-family boundary, **not
the cause of the gap**. Source gaps can be original disconnect
OPEN receipts, recovered CLOSE receipts, exact restored/rotated
named witnesses, or another fixed type. They have immutable
historical start/end boundaries but their real PAPER receipt
clock is assigned at the serialized record pump. A gap may be
processed after a packet's raw first-received timestamp was
captured, yet before that source packet was accepted by the
pump. This differs from an actual reversed venue L2 exchange
clock or two children of the same allMids frame.

Picking an upstream code repair before separating the gap
types risks corrupting source chronology or false-certifying
a structurally incomplete market. Those source gaps must
still make a clean 72h original-source campaign ineligible.

## This bounded causal experiment

The original v3 capture now tracks ONLY the *immediately
preceding* record's fixed gap reason bucket and OPEN/CLOSED
observation class. On a true adjacent-original clock
reversal where the preceding family was `data_gap`, it
increments a fixed 3 x 6 matrix keyed by open/closed/invalid
and whitelisted gap-reason buckets, including an `other`
bucket for unknown/untrusted input.

- The FIRST offending predecessor gap reason and open/closed
  class become negative-only fields.
- The full fixed histogram is written to both live diagnostic
  memory and the exact terminal negative receipt.
- A separate invariant compares the histogram's entire count
  with the original `data_gap -> *` adjacent source edges;
  PAPER-highwater-only regressions must not inflate it.
- The public heartbeat shows only the first safe reason and
  top four validated fixed buckets, plus an independently
  recalculated reconciliation flag. Raw stream IDs, payloads,
  arbitrary reasons, event keys, market identifiers and
  potentially secret source labels never enter the display.
- Tests reproduce real OPEN disconnect inversion, CLOSED
  recovery inversion, unknown reason bucketing, a future
  PAPER clock with **no adjacent original inversion**, false
  source integrity, raw-data preservation and hostile
  crafted public diagnostic keys.

This is **not** a fix for clock reversal. It is the missing
specific source-causality evidence needed to choose between
disconnect scheduling, recovery receipt placement, rotation
or an unrelated gap producer in the next natural worker.
The existing recorder's permanent failure, row loss, gap
sealing and qualification rules are untouched.

No source timestamp, journal row, normalized price, risk
limit, trade entry/exit, commission, funded account, restart
or LIVE setting changes. An accepted maker-versus-IOC
profit trial still requires a NEW independently authenticated
72h zero-gap mainnet source, two truly capital-matched full
after-cost PAPER ledgers, **both strictly positive** with a
strictly positive candidate uplift.
