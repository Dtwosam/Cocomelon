# Cocomelon Project Status

**Last updated:** 2026-09-21  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified implementation baseline:** `31a977ab2fd5fb6398314adf8c7b365e16b303f0`  
**Latest verified development CI:** run `35609936635` on PR #235 implementation head — success  
**Live trading:** **DISABLED**  
**Baseline edge:** **V4 RETIRED / TOUCHED — NO EDGE DEMONSTRATED**  
**Phase 10:** **OFFLINE LEARNING ENGINEERING ACTIVE; PROMOTION/LIVE BLOCKED**

## Current production state

The previously frozen V4 baseline `v4-baseline-4h-thesis-expiry` is retired under D-024. The user-authorized interim reveal permanently made that corpus TOUCHED / DEVELOPMENT-ONLY and showed negative gross and net expectancy. Future scheduled V4 economic acquisition and automatic V4 one-shot evaluation for that baseline are disabled.

The disclosed snapshot is bound to corpus artifact `10497424756` at exactly 100 closed trades / 18 closed-trade UTC days. The recorded development result was approximately:

- gross PnL: `-537.62`;
- net PnL: `-629.91`;
- mean net R: `-0.298`;
- profit factor: `0.44`;
- realized closed-trade maximum drawdown: `7.80%`.

This is failure/development evidence, not untouched OOS evidence and not a promotion claim.

The pre-retirement protected V4 acquisition `35524316366` finished successfully and naturally without cancellation, retry, extension, backfill, or outcome conditioning. The authoritative V4 synchronization/curation path accepted its actual interval into the retired touched corpus. Its data remains historical/touched and cannot restore promotion eligibility for the retired baseline.

## Trusted V4 dashboard state

Latest trusted Evidence Dashboard snapshot, refreshed **2026-09-21 10:41 UTC**:

- **69 accepted V4 cohorts**;
- **121 closed paper trades**;
- **21 closed-trade days**;
- **7,250 strategy decisions**;
- economic edge: **RETIRED / TOUCHED — NO EDGE DEMONSTRATED**;
- V4 one-shot state: **retired / touched; automatic evaluation disabled**;
- future V4 scheduler state: **retired**;
- live orders: **DISABLED**.

The additional cohorts after the 100-trade reveal are historical/touched observations. They are not a continuation of untouched promotion evidence and are not used to retune the already frozen r2 thresholds.

## Active research frontier

Development now proceeds under D-023/D-024/D-025. Research remains **TOUCHED / NON-PROMOTIONAL** until a future candidate is frozen and earns clean validation.

Primary development plan:

### Historical two-sided directional learning

Active plan: `docs/superpowers/plans/2026-09-21-historical-directional-learning.md`.

The product target is now explicit: study trustworthy historical behavior across eligible coins and estimate side-specific forward opportunity, then choose **LONG**, **SHORT**, or **NO_TRADE**. No permanent LONG-only or SHORT-only product rule is allowed.

Phase 9 has satisfied its exit criterion in the honest-failure sense: the retired V4 baseline failed to demonstrate edge. Therefore Phase 10 **offline learning engineering is active**. This opens historical dataset, feature, model-training, and challenger-evaluation work only; live trading and promotion remain blocked.

Current historical-learning implementation frontier:

- deterministic bounded candle backfill windows respect the existing 5,000-candle request ceiling;
- exact future-return labels record both LONG and SHORT gross outcomes;
- missing exact future target candles are excluded rather than approximated across gaps;
- mixed markets, mixed intervals, duplicate timestamps, empty source identity, and non-positive close prices fail closed;
- resumable public-mainnet candle and funding acquisition persists raw page envelopes plus normalized records;
- source manifests carry deterministic checksums, request/observed coverage, and gap state;
- overlapping funding page boundaries are authenticated/deduplicated and conflicting duplicates fail closed;
- the offline acquisition command supports multiple canonical markets and candle intervals through the existing rate-budgeted `InfoClient`;
- a deterministic combined coverage report records candle/funding provenance by market/interval/source;
- outcome and source identity/provenance remain model-agnostic;
- no model family or trading threshold has been prematurely selected.

PR #235 implementation head `0b463d515b2f0914a1ff7aae5ddc8682a12b931d` passed CI run `35609936635`: compile, Ruff, strict mypy, full pytest, and research smoke.

Next implementation work is Slice C: reconstruct point-in-time candle/funding features, represent historically unavailable fields explicitly, join features to exact directional outcomes, and export versioned columnar training datasets.

### Preserved r2 experiment

`research-r2-short-trend-quality-v1` remains immutable and auditable as a bounded touched short-side hypothesis, but D-025 removes it as the product architecture and as the sole gate to Phase 10 engineering.

Its last trusted dashboard state remains:

- registry state: **draft**;
- authenticated checkpoints: **0**;
- closed research trades: **0**;
- parent: `scheduled-research-root`;
- pinned strategy code revision: `2ce088d69df01f044b0650b811b51015a5edda51`;
- execution max position age: **20 minutes**;
- frozen research-only filter: trend-led SHORT with baseline score **72–81 inclusive**.

The failed natural r2 attempt from campaign `35551385941` remains historical/auditable and **NOT COUNTED**. PR #228 fixed the replay-identity fanout defect for future research, but the failed interval is not retried or backfilled.

### Current root/reference research state

Trusted Research Dashboard snapshot, refreshed **2026-09-21 09:58 UTC**:

- `scheduled-research-root`: **13 authenticated checkpoints**, **10 closed trades**, **7 closed-trade days**, cumulative touched net PnL about `-37.2371`, mean net R about `-0.14895`;
- legacy `research-r1-exit-15m-v1`: **7 checkpoints**, **6 trades**, **4 days**, cumulative touched net PnL about `-36.9098`, mean net R about `-0.24607`;
- r2: **0 authenticated checkpoints**.

None of these research results establishes verified edge.

## Research gates

Locked D-023 rules remain for registered touched economic candidates such as r2:

D-025 additionally requires historical-learning candidates to use point-in-time features, explicit future-only labels, chronological train/validation/test splits, and walk-forward evaluation. Historical development/backtest results are touched research and cannot become promotion evidence retroactively.

Locked D-023 rules remain:

- candidates may fail fast; candidates may not succeed fast;
- minimum economic futility sample: **20 closed research trades**;
- reject for futility at >=20 trades if `P(mu > 0) < 0.05`;
- `RESEARCH_PROMISING` requires at least **40 closed research trades**, **7 distinct closed-trade UTC days**, `P(mu > 0) >= 0.80`, complete costs, and no integrity/contamination/hard-risk issues;
- `RESEARCH_PROMISING` is still TOUCHED / NON-PROMOTIONAL;
- any future clean validation begins only after candidate freeze, inherited touched-period handling, and the documented six-hour embargo;
- live promotion still requires every gate in `MASTER_SPEC.md`, including >=500 closed mainnet paper trades and >=45 calendar days of shadow operation.

## Control-plane state

The authoritative V4 interval/completeness synchronization path is implemented in `.github/workflows/research-v4-registry-sync.yml`; research admission continues to rely on actual authoritative coverage/disjointness rather than nominal scheduler timing.

PRs #205–#234 establish the merged frontier; PR #235 is the verified historical-source-acquisition development slice:

- #205 added the deterministic r2 short-trend quality strategy seam;
- #206 registered and activated r2 as the research challenger default without dispatching economic evidence;
- #207 retired future V4 acquisition/automatic one-shot evaluation for the disclosed failed baseline;
- #208 restored pre-publication and final rollout-verifier enforcement for root+r2;
- #209 made the trusted dashboard one-shot state retirement-aware;
- #210 made r2 natural research the active execution plan and reconciled status with D-024;
- #211 made strategy-driven paper stop tightening update the materialized account atomically and survive restart;
- #212 refreshed the portable project handoff to the current r2 frontier;
- #214 advanced the active r2 plan through the verified stop-durability fix;
- #215 made paper restart reconciliation fail closed when the deterministic current `paper_position_events` record is missing or corrupted;
- #217 regression-locked LONG/SHORT tightened-stop restart durability and durable-write failure behavior;
- #219 made existing paper execution stores reject missing/unsupported schema versions without rewriting persisted metadata;
- #220 made journal/replay stores reject missing/unsupported schema versions without rewriting persisted metadata;
- #222 made durable paper order-plan write failures degrade execution health and block subsequent new exposure;
- #223 validates active-position opening-plan lineage on restart and runtime exit planning, failing closed on missing, unreadable, or tampered lineage;
- #224 makes funding-idempotency read errors degrade execution health before funding accounting can mutate state;
- #226 requires supported-version paper and journal/replay stores to be structurally complete before migration DDL, preventing deleted required tables from being silently recreated;
- #228 scopes research replay-run uniqueness to `(candidate_id, replay_run_id)` and transactionally migrates the legacy global-unique registry, allowing root+r2 to share one deterministic capture replay identity while preserving per-candidate duplicate protection;
- #230 attributes raw candidate-local terminal runner errors to the `evaluate-research` stage in the trusted dashboard while preserving upstream `WorkflowFailure` stage parsing and NOT COUNTED accounting;
- #232 makes paper restart reconciliation authenticate persisted execution attempts and fills, verify deterministic IDs/canonical payloads/plan ownership/fill lineage and aggregate fill accounting, fail closed when execution history exists without account state, and reject new fill writes whose `attempt_id` does not match the deterministic execution attempt;
- #234 makes historical LONG/SHORT/NO_TRADE learning the primary offline architecture and adds the first exact directional-outcome plus candle-backfill substrate;
- #235 adds resumable funding acquisition, deterministic coverage reporting, and the multi-market historical backfill command; implementation CI `35609936635` passed before documentation closeout.

Post-#232 main CI `35596674099` passed compile, Ruff, mypy, full pytest, and research smoke. Research Dashboard refresh `35586218717` remains the latest trusted research snapshot and renders the historical failed r2 attempt with failure stage `evaluate-research` while leaving it failed / NOT COUNTED.

## Exact next action

1. Keep live trading disabled and all hard risk limits unchanged.
2. Treat `docs/superpowers/plans/2026-09-21-historical-directional-learning.md` as the primary development plan.
3. Preserve V4, r1, and r2 artifacts/results as touched historical research; do not rewrite or relabel them.
4. Observe the implemented authoritative V4 interval/completeness synchronization path before admitting any future registered economic research; use actual authority state, not nominal scheduler timing.
5. Treat Slice B historical source acquisition as implemented and verified; preserve its raw-page/manifests/checksum contracts.
6. Reconstruct point-in-time historical feature rows using only data known at each anchor timestamp.
7. Represent unavailable historical microstructure/OI fields explicitly rather than synthesizing them.
8. Join those features to exact multi-horizon LONG/SHORT outcomes and export versioned columnar training datasets.
9. Establish simple direction-neutral baselines before adding more complex supervised models.
10. Train/evaluate chronologically with embargo and walk-forward splits; select LONG, SHORT, or NO_TRADE from cost-adjusted evidence.
11. Freeze any promising model/config before future untouched validation; historical development data remains touched.
12. Require every existing clean-validation, >=500-paper-trade, >=45-day-shadow, risk/integrity, and explicit live-authorization gate before capital is exposed.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in evidence or research lanes.
- Do not weaken risk limits, provenance, overlap, replay completeness, attestation, authentication, daily research caps, or rollout-verifier gates to accumulate trades faster.
- Do not treat later V4 cohorts as fresh promotion evidence for the retired baseline.
- Do not relabel touched research as untouched OOS evidence.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

**LIVE TRADING: DISABLED.**
