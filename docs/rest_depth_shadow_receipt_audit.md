# Independently audit PAPER REST shadow poll slots and original receipts

This is an **offline research verifier**. It does not connect to Hyperliquid,
place orders, change PAPER account state, modify market event signatures or
authorize LIVE trading. It also **does not** prove other processes sharing
the runner's public IP are known; that remains a separate activation gate.

The forward REST depth observer must emit **one receipt per frozen market per
scheduled polling tick**, including periods where its event loop arrived too
late to issue a request. Previously a 180-second window with most ticks
silently missed could be called "observation_window_completed" merely if
each market showed two distinct snapshots. Now each missed poll emits
\`missed_poll\` as **not fresh source evidence**, and any absent or missed
tick makes the source-window completion test fail.

A receipt has its \`slot_index\`, market identity, local monotonic elapsed
time, UTC receive clock and a nonexecution flag. A successfully received
book also carries source venue timestamp, source age, exact bid/ask depth,
and SHA-256 of the diagnostic public book message. Errors, missing slots,
denied shared quota, and shadow-slice exhaustion are recorded separately.

Offline verification of an explicitly enabled, independently captured
research artifact:

    python -m cocomelon.research.rest_depth_shadow_receipt_audit \
      --summary rest-depth-research-only-*/summary.json \
      --receipts rest-depth-research-only-*/shadow-attempts.jsonl \
      --output audited-rest-shadow-receipts.json

(Use one exact folder, not a shell expansion containing multiple sessions.)

The auditor requires:

- Exact schema, exact BLUR/BOME/CASHCAT cohort, permitted schedule interval,
  and all expected tick/market pairs appearing **exactly once**.
- Full original JSONL SHA-256 and consistent producer counters for HTTP,
  quota denials, misses, invalid books, duplicates, shallow books, future
  source timestamps and regressions.
- No fabricated source book on skipped/failed polls, valid 20x20 depth,
  strictly increasing source timestamps for unique books, identical source
  identity on duplicate observations.
- Per-receipt source-age arithmetic, consistent independently sampled UTC
  and monotonic clocks, and a reported end time consistent with the
  receipt-derived elapsed window.
- Independently recomputed per-market elapsed source freshness below the
  **unchanged** three-second and five-second source-age thresholds.
- Explicit false values for all source-authorization, account mutation,
  external-IP verification and profitability claims.

An entirely missing slot or a corrupted, edited or inconsistent report
causes the command to exit nonzero without a qualifying verdict. A fully
reconciled run can be labeled **clean research receipts** only if the
three-market time window is complete, the observer's stricter diagnostics
are healthy, and no duplicate is misrepresented as a fresh new book.

Even a clean receipt audit is **not cryptographic venue attestation**,
source completeness, unshared public-IP verification, after-fee strategy
profitability, or any permission to execute. Existing WebSocket signed
market history and PAPER authority remain exclusive until separately
validated. The observer remains default-off in the worker, and the
existing workflow sets neither activation flag.

Tracking: [#1243](https://github.com/Dtwosam/Cocomelon/issues/1243).


## Hard HTTP 429 circuit proof

A single REST HTTP **429** on any observed market trips a global low-priority
shadow stop. Every subsequent slot must be logged as
`rate_limit_circuit_open` with **no exchange request**. Already issued
same-tick requests may finish, but retries or new requests at later ticks
are forbidden. The offline auditor verifies the first 429 receipt, all
subsequent slot statuses, cumulative error and circuit counters, and the
independent `rate_limit_circuit_open` summary flag. A record indicating
later HTTP polling makes the whole research artifact nonqualifying.
This cannot validate other processes behind the same IP.
