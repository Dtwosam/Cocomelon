# R2 Natural Research Validation Plan

**Status:** active  
**Created:** 2026-09-20  
**Updated:** 2026-09-21  
**Supersedes for active execution:** `2026-09-14-research-natural-rollout-validation.md`  
**Scope:** touched research validation of `research-r2-short-trend-quality-v1`; paper/shadow only.

## Goal

Evaluate the immutable r2 short-trend quality challenger on naturally acquired, provenance-validated public Hyperliquid mainnet research cohorts without retuning it from the same disclosed V4 development sample and without weakening risk, overlap, daily-cap, replay-integrity, promotion, or live-order guards.

The failed V4 baseline is permanently TOUCHED / DEVELOPMENT-ONLY under D-024. R2 is a hypothesis generated from that touched sample, not evidence of edge. Its next information must come from new natural research cohorts.

## Locked candidate

- Candidate: `research-r2-short-trend-quality-v1`.
- Parent: `scheduled-research-root`.
- Strategy code revision: `2ce088d69df01f044b0650b811b51015a5edda51`.
- Execution horizon: 20 minutes.
- Starting paper cash: 10,000.
- Entry-quality rule: retain only trend-led SHORT decisions with baseline score 72–81 inclusive.
- LONG decisions, non-trend leaders, and scores outside 72–81 are vetoed to NO_TRADE.
- Risk limits remain unchanged.
- Live orders remain disabled.

These thresholds are immutable for r2. Later V4 cohorts and future r2 outcomes may not be used to silently retune this candidate.

## Current verified state

- Main implementation through PR #228: `9cdb68b5df8cdf1a21cde86d70a01dfc7d632600`.
- Post-merge main CI `35576633597` passed compile, Ruff, mypy, full pytest, and research smoke.
- PR #211 made existing `TIGHTEN_STOP` paper-execution actions durable across restart by atomically persisting the tightened materialized account state.
- PR #215 reconciles each current materialized paper position against its deterministic immutable `paper_position_events` record and fails closed on missing/corrupted event evidence.
- PR #217 regression-locks LONG/SHORT tightened-stop restart durability plus durable-write failure behavior.
- PRs #219/#220 reject missing or unsupported persisted schema versions for paper execution and journal/replay SQLite stores instead of silently rewriting metadata.
- PR #222 fails closed on durable order-plan write errors; #223 validates active-position opening-plan lineage; #224 fails closed on funding-idempotency read errors; #226 rejects structurally incomplete supported-version paper/journal stores before migration DDL can conceal table loss; #228 fixes shared root+r2 replay identity ownership in the research registry. These changes do not modify r2 entry thresholds, risk limits, cadence, or live-order controls.
- The revealed V4 baseline is retired from future scheduled acquisition and automatic one-shot evaluation.
- Protected pre-retirement V4 acquisition `35524316366` finished naturally; authoritative sync/curation accepted it into the retired touched corpus, now 69 accepted cohorts / 121 closed paper trades / 21 closed-trade days.
- Natural root+r2 campaign `35551385941` passed shared-capture, V4 completeness/disjointness, pre-publication rollout verification, and independent final rollout verification. Root succeeded and became checkpoint 13; r2 failed NOT COUNTED because the registry incorrectly made shared deterministic `replay_run_id` globally unique.
- PR #228 fixes that operational fanout defect for future natural cohorts via candidate-scoped replay uniqueness plus legacy-registry migration. The failed r2 attempt is not retried or backfilled.
- Trusted evidence dashboard reports the V4 baseline as RETIRED / TOUCHED — NO EDGE DEMONSTRATED.
- Trusted research dashboard lists r2 as draft with zero authenticated checkpoints.
- PR #208 restored both authoritative rollout-verifier gates for the active root+r2 pair.
- No manual economic research dispatch is authorized merely to accelerate evidence.

## Task 1 — Let the final protected V4 interval resolve naturally

- [x] Let run `35524316366` reach terminal state without cancellation, retry, extension, or outcome conditioning.
- [x] Preserve its actual run/job/session interval in V4 authority.
- [x] Require authoritative completeness/disjointness before any subsequent research economics are admitted.
- [x] Do not create any replacement V4 promotion sample for the retired baseline.

## Task 2 — Validate the first natural root+r2 cohort

Natural campaign `35551385941` exercised this contract. Root succeeded; r2 failed operationally before checkpoint commit because of the replay-identity registry defect fixed by PR #228. The failed r2 attempt remains auditable and NOT COUNTED; it is not retried or backfilled.

- [x] Require bot-controlled safe-gap dispatch; do not manually dispatch the economic campaign for proof.
- [x] Require exactly one authenticated public-mainnet capture shared by root and r2.
- [x] Require exact source ID, capture interval, recording-session digest, and source-set digest agreement.
- [x] Require root success; challenger failure remains auditable and nonfatal only where the locked verifier contract permits it.
- [x] Require `Verify root+challenger rollout contract before authoritative publish` to pass before an r2 checkpoint can become authoritative.
- [x] Require the independent final rollout verifier to pass.
- [x] Require actual V4 interval disjointness and completeness, not nominal cron assumptions.
- [x] Count only authenticated successful checkpoints.

## Task 3 — Evaluate r2 without moving the goalposts

- [ ] Before 20 closed r2 research trades, report evidence as insufficient and do not infer edge.
- [ ] At >=20 closed r2 trades, apply only the precommitted Bayesian futility rule: reject if `P(mu > 0) < 0.05`.
- [ ] Do not mark r2 `RESEARCH_PROMISING` before >=40 closed trades, >=7 distinct closed-trade UTC days, `P(mu > 0) >= 0.80`, complete costs, and clean integrity/risk state.
- [ ] Keep all positive research TOUCHED / NON-PROMOTIONAL.
- [ ] Do not create r3 merely because a few r2 trades disappoint or outperform; require a documented, testable new hypothesis and inherited touched lineage.

## Task 4 — Future clean validation only after research success

If r2 legitimately reaches `RESEARCH_PROMISING`:

- [ ] Freeze the challenger specification and all execution/risk semantics.
- [ ] Apply inherited touched-period handling and the documented six-hour embargo after the latest inherited touched interval.
- [ ] Start a new clean validation sample only after freeze/embargo.
- [ ] Require untouched OOS, walk-forward, cost-complete, drawdown, concentration, and all other locked promotion evidence.
- [ ] Keep Phase 10 and live trading blocked until the source-of-truth promotion gates are satisfied.

## Hard prohibitions

- No Hyperliquid testnet.
- No live wallet/order/transfer/withdrawal behavior in research/evidence workflows.
- No manual economic dispatch, retry, extension, cancellation, or backfill to accelerate results.
- No relabeling the disclosed V4 corpus as untouched evidence.
- No threshold retuning of r2 from later V4 outcomes.
- No risk-limit loosening to make a candidate appear profitable.
- No shortcut from touched research to Phase 10 or live orders.
