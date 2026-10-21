# Minimal independent flow-exhaustion PAPER runner

Current explicit owner instruction: build and safely launch the existing frozen
policy, without new strategy research or changes to protocol SHA256
c248746bbe4cd36fa63233b32bd643e368f2d20c63b0e973cf39ffd515873057.
Execution is autonomous within this request. No ordinary-worker or PR1392 change.

## Design and boundaries

Reuse existing PaperExecutionAdapter, risk engine, IOC/planner/accounting/funding
functions, and native eligibility. Add only trial-specific orchestration, original
source custody/validation and isolated activation/recovery. Candidate/control
receive distinct immutable IDs, separate SQLite stores and a leased trial root.
The control never takes a position. Original protocol bytes are read-only.

Durably stage opening intent before one post-latency IOC attempt per epoch;
recover committed fills without replaying an already attempted opening. Persist
frozen target/stop/first-fill, latched protective exit and pending hourly funding
liabilities before effects. Partial/failed exits retry remaining quantity on fresh
books even when entries are disabled. Actual settled funding received after close
must book idempotently from boundary quantity/oracle without waiting to protect
the position. Cash/fill/account state and trial checkpoint reconcile fail-closed.
Every raw frame/event/gap/decision/rejection/attempt/fill/mark has original clocks,
monotonic receipt ordinal and durable custody. No retiming or candle inference.

Source supports native broad discovery and unchanged eligibility, only genuine
info/WS data, original ordered tape and complete book windows. Clock/gap/funding
uncertainty blocks new entries while management continues. A source label/boolean
or local hash does not establish independent authenticity or resource ownership.

## Operational launch gate

User conditionally authorizes launch. Current independent review finds no owned
egress/resource proof or observed qualifying full-depth<=2s feed. Standard hosted
VM separation is not public-IP isolation; existing ordinary budget peaked1000.
Prior default20level WS receipts were~5.4s; fast5level substitution is not admitted.
No source/network process starts from this work without verified operational
evidence. Missing resource/source is an activation blocker, not permission to skip
implementing and testing the account/execution runner. No synthetic activation
receipt or current first-entry boundary will be invented. At authorized launch,
immutable receipt binds code/protocol/account/source/resource and future boundary
>=release+6h. Preserve14/28day review contracts and losses.

## Tasks

- [x] Refresh main, permanent mandate, PR1393, PR1392, actual worker/jobs/source/usage.
- [x] Identify concrete source/resource blockers without another market-data probe.
- [x] Test-first implement trial engine + real adapter accounting/restore safeguards.
- [ ] Test-first implement original source custody/quality/eligibility integration.
- [ ] Implement isolated root/lease/account IDs/activation receipt and specific CLI.
- [x] Independently review exact protocol/clock/funding/partial-fill/restore boundaries.
- [ ] Run focused checks and exact-head full/researchCI; ship justified slice.
- [ ] Activate only if independent source/resource/custody gates actually pass;
      otherwise retain inactive and report exact bounded blocker, no fabricated PnL.

## Owner scope refinement: bounded feed feasibility

The owner's follow-up explicitly rejects further speculative infrastructure.
Existing provider credentials/fan-out and owned egress were not established.
[Bounded service/cost investigation](../../flow_exhaustion_feed_feasibility_2026_10_21.md)
identifies a $200/month feed candidate, unmeasured and not admitted. Finish only
the necessary independent execution/account core and its safety review now.
Defer source integration, operational CLI, real trial-account preparation and
activation receipt until authorized evaluation access proves the source contract.
No actual first-entry boundary or accounts are allocated in this slice.
This supersedes the original broader task list above; deferred items are blockers,
not completed work.
