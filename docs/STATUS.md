# Cocomelon Project Status

**Last updated:** 2026-08-23  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`

## Current state

**Last completed phase:** Phase 6 — independent risk engine  
**Integration state:** MERGED into `main`  
**Phase 6 PR:** #8  
**Phase 6 merge commit:** `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`  
**Final Phase 6 PR head:** `09a7fc7c3ed611d700905081cb2b606d52b558d4`  
**Final Phase 6 PR-head CI:** `32663669112` — SUCCESS  
**Final Phase 6 CI job:** `97253567901`  
**Active next phase:** Phase 7 — real-mainnet paper execution + position manager

## Phase 6 established

Phase 6 is the authoritative deterministic new-exposure risk gate between Phase 5 strategy output and future execution.

Implemented:

- immutable Decimal `RiskLimits`, `RiskAccountState`, `OpenPositionRisk`, `RiskHealthState`, `ExecutionCostEstimate`, `LiquidityRiskState`, `RiskRequest`, and `RiskDecision` contracts;
- deterministic risk/account IDs and stable reason/binding-cap normalization;
- 0.25% cost-aware planned risk per trade;
- 0.75% aggregate planned-open-risk ceiling;
- 0.50% conservative correlation-bucket ceiling with no directional risk netting;
- 1.00% daily realized-loss lockout;
- 3.00% rolling weekly drawdown lockout;
- three consecutive losses -> 60-minute cooldown;
- same-market exposure veto, preventing averaging down/add-on entry through the public new-exposure pathway;
- stale/future/inconsistent risk, market, liquidity, account, and execution-health rejection;
- system gross leverage cap of 3x or lower venue maximum;
- new exposure limited to 50% of available margin after effective leverage;
- new notional limited to 10% of the weaker visible 25-bps entry/exit side depth;
- LONG/SHORT liquidation checks requiring liquidation beyond the stop and at least 2x stop distance;
- venue minimum notional rejection without forced upsizing;
- conservative risk-budget-to-notional Decimal division using downward rounding;
- fixed 28-digit authoritative Decimal arithmetic context so replay is not affected by ambient process precision/rounding;
- source-level architectural boundary tests excluding order placement, wallet/signing, exchange account APIs, fill simulation, ML, averaging-down, and martingale capability from the risk package;
- deterministic invariant matrices proving higher strategy score, higher execution costs, lower margin, or lower liquidity cannot improperly increase exposure.

The risk engine returns only APPROVE/REJECT approval envelopes. It does not place or simulate orders.

## Phase 6 verification evidence

Final feature head before merge:

- head: `09a7fc7c3ed611d700905081cb2b606d52b558d4`;
- CI run: `32663669112` — SUCCESS;
- CI job: `97253567901`;
- Python: `3.12.14`;
- editable install — PASS;
- `python -m compileall -q src tests scripts` — PASS;
- Ruff (`src tests scripts`) — PASS;
- mypy (`src`) — PASS;
- pytest — PASS to 100%.

Late safety audit deliberately caught two issues before merge:

1. Default Decimal half-even division could round a repeating risk-budget quotient upward, causing planned risk to exceed the cap by one Decimal unit. A RED regression demonstrated `25 / 0.0224` producing a notional whose recomputed risk was `25.00000000000000000000000001`. The fix introduced downward risk-to-notional division; the regression then passed.
2. Authoritative risk results inherited ambient process Decimal precision/rounding. A hostile-context RED regression changed precision to 8 and rounding to `ROUND_UP` and produced a different approval. The fix wrapped the entire authoritative pipeline in a fixed 28-digit half-even context while retaining downward risk-to-notional division. The final full suite passed.

PR #8 was marked ready only after final verification and had no unresolved review threads. It was merged with expected-head SHA protection using exact head `09a7fc7c3ed611d700905081cb2b606d52b558d4`. GitHub returned merge commit `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`. Immediately after merge, `main` was verified at that SHA. Comparing `main` to `phase-6-independent-risk` showed the feature branch behind by exactly the merge commit, ahead by 0, with an empty file diff.

## Phase 6 exit-criteria audit

Verified against the approved Phase 6 design:

- old float risk placeholder replaced by immutable Decimal contracts;
- deterministic tests cover every locked risk rule;
- strategy score cannot override or scale the risk budget;
- risk approval cannot place orders;
- adverse/missing/stale/inconsistent state fails closed;
- estimated entry slippage, stop slippage, and round-trip fees consume the risk budget;
- aggregate and correlation limits are enforced with absolute planned loss and no default directional netting;
- same-market add-on exposure is rejected;
- rejected decisions always expose zero approved risk/notional;
- risk-to-notional rounding cannot exceed the approved risk budget;
- authoritative results are independent of ambient Decimal context;
- full Python 3.12 install/compile/Ruff/mypy/pytest CI passes;
- live trading remains disabled.

## Completed phases

- Phase 0 — governance/source-of-truth anchor: COMPLETE.
- Phase 1 — Python foundation/domain/config/CI: MERGED at `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`.
- Phase 2 — mainnet REST discovery/normalization: MERGED at `b95352e238d6a9eabd63e13c1f8300e654a7e636`.
- Phase 3 — WebSocket collector/durable recorder: MERGED at `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57`.
- Phase 4 — feature engine/scanner/ranking/shortlist: MERGED at `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6`.
- Phase 5 — explainable baseline strategy engines: MERGED at `82c3db2f9ce39676e089eac79e63c5043b72e331`.
- Phase 6 — independent risk engine: MERGED at `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`.

## Safety invariants still locked

- Hyperliquid testnet is forbidden.
- Runtime observations remain Hyperliquid mainnet only.
- Default execution mode remains `paper`.
- Live trading is disabled.
- No live exchange adapter exists.
- Strategy cannot size positions or send orders.
- Risk is independent and authoritative over strategy output.
- Phase 7 may execute less than a risk approval but never more without a fresh risk decision.
- No ML/learning engine exists yet.
- No wallet signing, transfer, or withdrawal capability exists.
- No averaging down or martingale.
- Solidity is not part of V1.
- No secrets may be committed or emitted in logs.

## Phase 7 objective

Phase 7 builds real-mainnet paper execution and position management while preserving the Phase 6 approval envelope as a hard ceiling.

Phase 7 must, at minimum:

- define an execution abstraction shared by paper now and live much later;
- translate approved notional into venue-valid quantity using actual instrument precision/minimum rules;
- consume real Hyperliquid mainnet book/trade observations only;
- model spread, visible-depth impact/slippage, fees, latency, partial fills where defensible, and execution failure without assuming perfect fills;
- create immutable order-plan/order-attempt/fill/position lifecycle records with deterministic IDs;
- prevent paper execution from exceeding approved notional/risk;
- support LONG and SHORT entry plus reduce-only exits;
- manage stop/invalidation exits and bounded intraday lifecycle actions without widening risk;
- keep account/position state deterministic and restart/reconciliation friendly;
- make paper fills auditable and replayable from recorded market evidence;
- keep all live signing/order submission disabled and outside the paper adapter.

Do not begin journal/backtest/ML/live phases early except for interfaces strictly required by Phase 7.

## Exact next action

1. Treat Phase 7 — real-mainnet paper execution + position manager — as active.
2. Re-read `AGENTS.md`, `docs/MASTER_SPEC.md`, `docs/DECISIONS.md`, `docs/BUILD_ORDER.md`, this status file, Phase 6 risk contracts, and existing market/event contracts.
3. Verify current official Hyperliquid mainnet instrument sizing, order semantics, fee/public-data behavior relevant to paper modeling.
4. Run the Phase 7 design/spec workflow before production implementation.
5. Write a detailed Phase 7 TDD implementation plan.
6. Implement on an isolated branch with no signing, wallet, private account API, or live order submission.

## Live trading status

**DISABLED.**

Cocomelon can now generate explainable LONG/SHORT/NO_TRADE strategy decisions and independently approve/reject bounded exposure on deterministic inputs. It still cannot send a real exchange order. Phase 7 is paper execution only.
