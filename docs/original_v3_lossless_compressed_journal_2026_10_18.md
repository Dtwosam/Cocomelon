# 2026-10-18 — Lossless original v3 PAPER journal compression

The real worker #39120486505 has recorded **2,557,356** original source
offers, **1,421** durable entries and **2,555,935** dropped rows at its
13:56 UTC authenticated heartbeat. Its raw first-received clock
regressions and market L2 gaps make that archive permanently **invalid**.
The genuine $10,000 PAPER account had **291 closed trades** and marked
after-cost equity **$9,736.88**, or **−$263.12** net. This change does
not repair that archive or retrospectively grant market coverage.

## Implementation — exact at-rest encoding, not a source filter

New workers use optional `compressed_journal=True` in the existing
separate nonblocking v3 original capture writer; direct legacy capture
callers stay plain JSONL for backward-compatibility. The only difference
is the physical file:

- Plain legacy: `original-received-rows.jsonl` with the original
  480MiB physical and decoded cap.
- New compressed mode: `original-received-rows.jsonl.gz`, a stream of
  **concatenated, independently fsynced gzip members**. Each accepted
  writer batch is compressed completely, then appended atomically from
  the research writer's perspective without ever blocking PAPER's
  event loop. The existing strict 5M row and 480MiB **physical disk**
  limits remain; decoded original row bytes are separately bounded at
  4GiB. No original event, timestamp, event key, receipt ordering,
  gap record, exchange-time, risk or fee is changed.
- The original writer SHA-256 continues to hash exactly the canonical
  **UNCOMPRESSED row bytes in original receipt order**. A compressed
  writer terminal records both actual physical and actual decoded byte
  counts plus a fixed journal-format ID. A storage-budget projection
  distinguishes compressed *physical* and decoded estimates; early
  failed written samples remain nonrepresentative.
- The source sealer selects the original representation from the
  CLOSED worker terminal, refuses ambiguous two-file formats or
  mismatched actual stored lengths, streams every decompressed original
  line, rechecks actual decoded byte and row counts, exact first-seen
  monotonic clock, original SHA256 and sealed ordinal parity before
  exposing an original ZIP or manifest. A malformed gzip CRC, torn
  member, wrong terminal format, budget mismatch or changed original
  SHA fails closed. The independent GitHub ZIP SHA/artifact identity
  source-custody gate is **unchanged**.

This can reduce physical disk pressure **only on a future worker whose
individual compressed archive fits its real 480MiB limit**. The encoding
may be a small or large gain depending on actual market-data entropy.
The merged 72h paired replay still requires >=18 separately genuine
4h original source workers with complete market clocks and reliable
signed handoff. No saved bytes prove a strategy is profitable.

## Hard limitations

The current source is not merely too large: it has very large true
received-clock regressions, significant stale L2 intervals, and many
true original gaps. Compression MUST NOT mark it qualified or hide any
dropped row. Existing signed account/after-cost trial gates, frozen
LONG+trend hypothesis, original after-cost economics and LIVE disabled
mode are untouched. The current PAPER worker is not stopped or reset
to adopt source storage code.

Unit tests compare exact decoded bytes and SHA to the true original
order across multiple independent gzip members, re-open the original
source as the existing sealed replay manifest, and inject CRC tampering,
truncation, source-format spoofing, terminal count/digest mismatch,
clock regression and source storage exhaustion. Green CI alone is NOT
validated positive PnL.
