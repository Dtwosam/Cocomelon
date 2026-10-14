# Paired full-depth source evidence screen

This command does **not** connect to exchanges, handle money, repair signed
market gaps, modify PAPER orders or authorize LIVE trading.

It consumes the original JSONL and summary artifacts produced by:

- The read-only public 20-depth probe, workflow
  "Independent Full-Depth L2 Cadence Probe".
- The optional hosted 20-depth per-block gRPC collector, workflow
  "Optional QuickNode Full-Depth gRPC Diagnostics". This is not currently a
  demonstrated paid-provider connection; results must not be invented.

Example, with two already-downloaded, extracted 180-second artifacts:

    python -m cocomelon.research.paired_full_depth_source_screen \
      --public-summary public/l2-cadence-probe/summary.json \
      --public-receipts public/l2-cadence-probe/source-receipts.jsonl \
      --candidate-summary hosted/grpc-l2-diagnostic/summary.json \
      --candidate-receipts hosted/grpc-l2-diagnostic/receipts.jsonl \
      --output paired-full-depth-screen.json

Both result archives must be **contemporaneous** and must match the exact
frozen 20-market cohort. Historical October 14 public baseline and a future
candidate **cannot be considered a paired test** if their observation windows
do not overlap by at least two minutes.

Fail-closed requirements:

- Original receipt JSONL SHA-256 equals the source summary's digest.
- At least 180 seconds of independently reported completed collection.
- Exact 20-market membership, at least 20 unique valid snapshots each market.
- Reported counts, timestamps and per-market time-weighted freshness reproduce
  from raw receipts within five basis points.
- Each original receipt's `receive_utc_ms - receipt_elapsed_ms` must refer to
  the **same observation start** (<=1000ms tolerance across the entire file).
  Its reconstructed finish must agree with the summary's declared finish
  within <=5000ms. The paired overlap is computed from **receipt-derived
  UTC start/end**, never from the summary timestamp alone. This prevents
  retroactively changing an old summary's end time to pose as a contemporaneous
  sample. Receipt checksums alone are not signatures or proof of clock truth.
- 20 bid and 20 ask levels for public and candidate books. Candidate must
  request 20 levels, have no source/parse errors, no height regressions,
  contradictory block records, future-dated books or shallow observations.
- Each source report is checked independently, including connection health;
  duplicates and out-of-order messages are not counted as fresh evidence.
- A *research-only* preliminary screen can pass only with at least 95% of
  elapsed time under the existing three-second source-age gate **for every
  candidate market**, plus a >=20 percentage-point improvement over public
  source on every market and >=120s paired observation overlap.

A screening pass **does not** prove the provider's source completeness,
latency advantage across other days or networks, independent clock accuracy,
authenticated trader continuity, 20-depth strategy eligibility, book
execution accuracy or profitable after-cost trading.

Even a passing screen **does not authorize production source integration**.
That requires a separate forward-only nonexecuting PAPER shadow and
independent source/ledger/after-cost gates. The existing three-second stale
gate, five-second strategy age, positions, fills and LIVE-off status remain
untouched. If any prerequisite is missing, the command exits nonzero and
reports no qualifying verdict.
