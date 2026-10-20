# Ordinary PAPER entry suspension

**Release status: IMPLEMENTED BUT NOT ACTIVE. Activation: BLOCKED FOR SAFETY.**
This preparation does not change the currently executing worker. No restart,
dispatch, stop-file write, account reset or position close is authorized by this
document. No profitable strategy has qualified for new allocation.

## Scope and enforcement

The ordinary continuous PAPER runtime constructs its execution adapter with
`entries_suspended=True` and its lifecycle with `new_exposure_cutoff_ms=0`.
The lifecycle does not stage or execute opening candidates. The adapter also
rejects direct opening submissions before planning, simulation or account writes.
There is no resume flag or API in this release. Shared research adapters retain
their existing defaults and cannot allocate the ordinary account.

Decision evaluation continues because position management uses current thesis
and invalidation information. Existing stop, thesis, tightening and emergency
management runs before the opening cutoff. Reduction quantity remains capped by
the existing held position. Partial fills, latency waits and retries retain the
existing accounting and restoration paths. LIVE controls are unchanged.

`paper-entry-suspension.json` in the existing state root stores policy origin,
not activation proof or entry authority. Missing legacy state boots suspended.
Malformed, false, future-clock or unwritable policy evidence also boots suspended;
invalid bytes are preserved and the durability diagnostic is negative. A policy
write failure does not make execution unhealthy or trigger an unnecessary exit.
The account/checkpoint schemas, historical trades and booked costs are unchanged.

Both fast and durable workflows already archive the entire state root. A
successor running this release restores original policy provenance and begins
with both entry guards enabled. An older binary may ignore the file: rollback
and each actual successor require independent code-head and runtime verification.

## Evidence and limits

Real-component tests exercise LONG/SHORT entry rejection, held stops and thesis
exits without flips, pre-existing opening candidates, partial IOC fills without
top-ups, reduction caps, protective retries, tighter stops, genuine SQLite and
lifecycle restoration, booked funding idempotence, account-write failure and
policy-write failure. Deterministic fixture books test software behavior; they
do not establish real-market fills or economic expectancy.

The existing adapter's pending-reduction cache is memory-only. A full-root
archive preserves durable plans, attempts, fills, held quantity and lifecycle
stops, but does not restore that exact transient queue. Handoff tests prove
protection can retrigger and finish a reduction after restore; they do not prove
the original in-flight reduction intent survives unchanged. Activation therefore
requires authenticated absence of pending reductions at transition, or separate
proof of safe recovery of every actual pending intent. This release does not
add a generalized pending-order persistence system.

Operational and full heartbeats, plus the session summary, carry policy origin,
durability, the actual adapter/lifecycle gates, session opening attempts/fills,
direct opening rejections and candidate/reduction queue counts. A zero direct
rejection counter does not count cutoff-suppressed decisions. Queue diagnostics
are scoped to the synchronous PAPER implementation, not a venue order inventory.
Legacy or malformed status remains UNVERIFIED. A runtime acknowledgment must be
bound to the separately authenticated worker run/head and timestamp.

## Natural transition admission

Keep this release unmerged until its exact-head full test and research CI pass
and the operational transition is independently shown safe and authorized.
No forced rollout is part of this work. Before an eventual natural transition:

1. Authenticate the predecessor run/head, account, held positions and all pending
   state; retain its exact authoritative state archive and lineage. Unknown
   pending state or an unverified in-flight reduction blocks activation.
2. Confirm the genuine successor lease, tested code head and complete state-root
   restoration. Do not duplicate a healthy trader or substitute an empty account.
3. Reconcile starting cash, all booked history/costs, held position quantities,
   lifecycle stops and pending reductions against the predecessor. Preserve
   identified pre-existing gaps; do not describe missing evidence as reconciled.
4. Require a fresh successor heartbeat with both actual gates enabled and zero
   session opening attempts/fills, alongside working account/position monitoring
   and protective management. Check durable journal/account state when available.
5. Verify subsequent successor acknowledgments and durable artifacts. A file,
   passing tests, workflow activity or a historical zero queue is insufficient
   to claim ACTIVE AND VERIFIED.

Any missing operational requirement leaves activation BLOCKED FOR SAFETY. The
existing selection investigation remains **UNRESOLVED — EVIDENCE INSUFFICIENT;
SHELVED**. No new mechanism passed economic admission, no experiment or selector
is added, and challenger capital stays NO_TRADE. **NO NEW ECONOMIC PROGRESS.**
