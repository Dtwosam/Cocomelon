# Phase 9 V4 Thesis-Expiry Evidence Design

## Problem

The V3 lifecycle-aware protocol fixed the paper reduce-only latency defect and extended each acquisition to four hours, but the frozen position manager has no time-based exit. A position exits only on critical health, a stop, or a fresh opposite thesis. A same-direction or `NO_TRADE` sequence can therefore leave a valid position open indefinitely.

Because V3 admits a cohort only when `opened_positions == closed_positions` at the fixed four-hour endpoint, accepted evidence is conditioned on whether trades happen to close within that window. Holding duration is price-path dependent, so this can right-censor the economic sample even though acquisition length itself is performance-blind.

No V3 cohort has been accepted. V2 and V3 remain historical protocol identities and must not be reinterpreted.

## Decision

Create a new V4 candidate/protocol with an explicit four-hour thesis expiry. This is an economic rule, not an evidence-only forced close: the baseline's directional inputs are short-horizon and the longest explicit return horizon used by the primary strategy set is four hours. A position that has survived four hours without hitting its stop or receiving an opposite fresh thesis is exited because the originating short-horizon thesis has expired.

The rule is precommitted before any V4 evidence is accepted and does not inspect PnL, final equity, profitability, win rate, or any evaluation metric.

## Position-management semantics

Add optional `PaperExecutionConfig.max_position_age_ms: int | None`, defaulting to `None` so all existing V2/V3 behavior is unchanged.

V4 sets `max_position_age_ms = 14_400_000` (4 hours).

Exit priority is:

1. critical execution/account health;
2. mark stop trigger;
3. fresh opposite strategy thesis;
4. thesis expiry when `timestamp_ms - opened_at_ms >= max_position_age_ms`;
5. tighter same-direction invalidation;
6. explicit validated reduction;
7. hold.

The expiry action uses `PositionActionType.EXIT_THESIS` with reason code `MAX_HOLD_EXPIRED`. It remains reduce-only, uses the existing planner/IOC/slippage/latency/depth/fee machinery, and can never bypass paper execution constraints.

## V4 replay identity

V4 must use distinct immutable identities from V2/V3:

- execution config version: `phase7-v2-4h-thesis-expiry`;
- replay engine version: `phase8-v3-thesis-expiry`;
- replay config version: `phase9-baseline-replay-v3-thesis-expiry`;
- source protocol: `v4-thesis-expiry-mainnet`;
- Phase 9 candidate: `v4-baseline-4h-thesis-expiry`.

The strategy signal engine and risk limits remain unchanged. Candidate identity changes because execution/position-management economics change.

## Acquisition window

V4 keeps the performance-blind 45-minute opportunity/entry window (`2700` seconds).

Total capture becomes 5 hours 15 minutes (`18_900` seconds). The latest possible entry occurs before minute 45; a four-hour thesis expiry therefore becomes due before 4h45m from recording start. The remaining fixed 30-minute closeout margin allows the normal reduce-only latency/IOC path to complete. If data are stale/gapped, replay is incomplete, or the position still cannot close through normal execution, the cohort fails closed.

No cohort is lengthened after observing trade state or economic outcome. No position is force-filled at the endpoint.

## Evidence admission

V4 retains strict admission requirements:

- genuine public Hyperliquid mainnet source only;
- paper execution only and `live_orders=false`;
- clean redundant transport with no unresolved gaps/anomalies;
- complete offline replay and evaluation dataset;
- fixed 45-minute entry cutoff;
- exact V4 runtime/protocol identity;
- final flat replay exposure;
- no PnL/performance value may affect retry, admission, corpus mutation, or capture length.

Flatness is now a protocol consequence for normally executable positions because all entries have a finite four-hour economic lifetime inside the fixed capture window, rather than a selection criterion that favors naturally short holds.

## Backward compatibility

V2 and V3 defaults remain unchanged:

- `PaperExecutionConfig.max_position_age_ms` defaults to `None`;
- V2/V3 replay helpers continue to construct the same execution semantics and version identities;
- existing V2/V3 artifacts, evaluators, and protocol hashes are not mutated;
- historical V3 diagnostics remain visible for audit but do not count toward V4 progress.

## Phase 9 boundary

V4 will get a distinct Phase 9 handoff after the core runtime is merged and pinned. The locked statistical policy is unchanged: at least 100 untouched OOS closed trades, 30 closed-trade days, walk-forward/sample-size rules, bootstrap policy, embargo, NO_TRADE horizons, concentration limits, and the same `CANDIDATE_EDGE` requirements.

The core runtime PR must merge before activation so acquisition and curator workflows can pin one exact immutable runtime SHA. No V4 source may be accepted from an unpinned or mixed runtime.

## Safety

- Hyperliquid testnet remains forbidden.
- Live orders remain disabled.
- No wallet/private-key or signing path is added.
- Stops remain mandatory and retain higher priority than thesis expiry.
- No averaging down or martingale behavior is introduced.
- The time stop cannot increase position size or create new exposure.
- Phase 10 remains blocked until the distinct V4 one-shot evaluation genuinely satisfies the locked gate.
