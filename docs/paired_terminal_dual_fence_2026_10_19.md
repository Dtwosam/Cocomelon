# October 19 — fence BOTH research accounts before either terminal checkpoint waits

## Money-relevant inconsistency

The historical v5 and v2 paired PAPER trials are already FAILED and must
never be repaired, truncated or promoted. The independently observed
legacy terminal archive includes signed account state that predates the
SQLite account ledgers by approximately 13.6 minutes. An October 19
repair (#1380) fences admission when each actor's terminal checkpoint
begins, but a SIDE-CAR scheduling hole remained:

1. The sidecar invokes and AWAITS the legacy actor's terminal checkpoint.
2. During that await, its completely separate trend actor still accepts
   new record, rank, warmup and universe-reconciliation mutations.
3. Only after the first actor's SQLite checkpoint completes does the
   sidecar fence and checkpoint the second actor.

The terminal pair can therefore cover *different original receipt
windows*, even if both component SQLite snapshots match their own signed
checkpoint. A relative PnL delta across those terminal windows is
not a trustworthy capital-matched outcome.

## New prevention

- Expose a synchronous, idempotent `fence_terminal_admission()` on each
  isolated research actor. It shares the existing admission lock with
  queued mutating events and does not flush, modify or re-sign account state.
- The sidecar fences BOTH actors immediately, without an `await` between
  fences, before beginning *either* slow durable terminal checkpoint.
  The primary-missing case still fences the newer actor before its separate
  mandatory negative receipt.
- The final checkpoint remains one-shot: pre-fencing does NOT consume the
  allowed checkpoint; a second checkpoint fails. The ordinary in-session
  checkpoint retains its preexisting nonterminal semantics.
- A deterministic asynchronous regression holds the first actor's checkpoint
  while trying to feed the second actor; neither actor can admit a later
  original market row. The second actor eventually signs its own queued
  original prefix and the negative authority flags remain.
- On-disk legacy roots, actual original source records, ordinary PAPER
  account, fees, funding, trading decisions, positions, risk and worker
  state are unchanged. No forced worker restart; LIVE remains disabled.

## Remaining qualification

This protects the admission cutoff, NOT atomicity across multiple SQLite
files, crash-consistent custody, market-source completeness, missing-gap
repair, or synchronized independent PnL. The failed historical campaigns
remain permanently failed. Future matched forward campaigns require
actual source integrity, verified independent signed account receipts,
strictly positive absolute after-cost account equities, and robust
positive challenger uplift. NO VERIFIED PROFITABLE EDGE.
