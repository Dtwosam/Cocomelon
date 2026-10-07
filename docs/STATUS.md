# Cocomelon Project Status

**Last updated:** 2026-09-22  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified implementation baseline:** `a54c7ed8dc773b056135c51983a7f4351bb82057`  
**Latest verified development CI:** post-merge CI run `35750670396` on `a54c7ed8dc773b056135c51983a7f4351bb82057` — success  
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

PR #236 implementation head `4c04600d5835197209c5405c9a05d992db38f78a` passed CI run `35613448712`: compile, Ruff, strict mypy, full pytest, and the research job with real PyArrow export. Slice C now reconstructs point-in-time candle/funding features from exchange timestamps, keeps later retrieval time explicit, refuses to bridge gaps, marks unavailable historical OI/L2/order-flow fields instead of fabricating values, authenticates normalized source files against manifests/checksums, joins exact LONG/SHORT outcomes, and exports versioned Parquet training datasets.

PR #237 implementation head `2e61ea9966e02475059e54b9c670d681ae4ae449` passed CI run `35614793455`: compile, Ruff, strict mypy, full pytest, and research smoke. Slice D now includes transparent shared cross-coin conditional baselines, minimum-sample coin calibration, separate LONG/SHORT expectancy estimates, strict chronological/embargo walk-forward folds, explicit fee/slippage plus conservative funding-reserve costs, validation-only NO_TRADE threshold calibration, shared-versus-coin comparison, and a regression proving future test outcomes cannot alter selected thresholds.

Next implementation work is to run the verified source→dataset→baseline pipeline on bounded real public-mainnet historical corpora, persist touched-development reports, then freeze only reproducible candidates that justify promotion into future clean paper/shadow validation.

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

PRs #205–#236 establish the merged frontier; PR #237 is the verified historical baseline-learning development slice:

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
- #235 adds resumable funding acquisition, deterministic coverage reporting, and the multi-market historical backfill command; implementation CI `35609936635` passed before documentation closeout;
- #236 reconstructs point-in-time historical candle/funding features, authenticates source manifests/checksums, joins exact directional outcomes, and exports versioned Parquet training corpora; implementation CI `35613448712` passed before documentation closeout;
- #237 adds direction-neutral shared/coin conditional baselines, chronological embargo/walk-forward evaluation, cost-aware validation-only NO_TRADE calibration, and explicit shared-versus-coin test reporting; implementation CI `35614793455` passed before documentation closeout.

Post-#232 main CI `35596674099` passed compile, Ruff, mypy, full pytest, and research smoke. Research Dashboard refresh `35586218717` remains the latest trusted research snapshot and renders the historical failed r2 attempt with failure stage `evaluate-research` while leaving it failed / NOT COUNTED.

## Exact next action

1. Keep live trading disabled and all hard risk limits unchanged.
2. Treat `docs/superpowers/plans/2026-09-21-historical-directional-learning.md` as the primary development plan.
3. Preserve V4, r1, and r2 artifacts/results as touched historical research; do not rewrite or relabel them.
4. Observe the implemented authoritative V4 interval/completeness synchronization path before admitting any future registered economic research; use actual authority state, not nominal scheduler timing.
5. Treat Slices B, C, and D as implemented and verified; preserve source/data manifests, temporal isolation, cost assumptions, and missing-feature semantics.
6. Run bounded touched-development historical experiments using the public-mainnet source→dataset→baseline pipeline.
7. Persist reproducible reports by market, regime, direction, horizon, fold, and shared-versus-coin variant; do not call them untouched OOS evidence.
8. Use those reports to decide whether a more complex supervised model is justified; complexity must beat the transparent baseline under the same chronological protocol.
9. Freeze any promising model/config/feature registry/data manifest/decision policy before future clean validation starts.
10. Keep NO_TRADE first-class and preserve every live/risk/promotion gate.
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


## Historical-learning frontier sync — 2026-09-21

Plain-English operating method:

1. Reconstruct only market information that genuinely existed at each historical timestamp.
2. Learn separate forward LONG and SHORT opportunity from many coins and horizons instead of hard-coding one direction.
3. Evaluate in chronological train -> validation -> test order with embargo; never random-shuffle time-series evidence or use test outcomes to tune the learner.
4. Subtract explicit fee, slippage, and conservative funding costs before treating any setup as edge.
5. Make NO_TRADE the economic baseline: if a validation policy is not positive after costs, doing nothing wins.
6. Require candidate edge to survive multiple chronological validation blocks; unstable aggregate performance is rejected even when its average looks attractive.
7. Prefer shared cross-coin learning first, with market-specific calibration only after enough chronological samples exist.
8. Keep historical results touched/development-only. A promising candidate must be frozen before future clean paper/shadow evidence begins.

Merged implementation frontier after PR #237:

- #239–#242 added the first bounded BTC/ETH/SOL/HYPE public-mainnet historical experiment, funding-cadence tolerance, truthful lineage labels, full loss diagnostics, and corrected same-corpus reruns.
- #243 made zero-return NO_TRADE dominate validation policies with non-positive realized net mean.
- #244 added a continuous regularized per-horizon ridge learner with train-only normalization and sample-gated market effects.
- #245 compared the transparent conditional baseline and ridge learner on identical authenticated data, folds, costs, and thresholds.
- #246 added horizon-specific validation abstention; it reduced some loss but remained net-negative and was not promoted.
- #248 added multi-block chronological validation stability gating. The stable ridge selected NO_TRADE in all tested folds, avoiding prior losses but demonstrating no repeatable edge.
- #251 reconstructed deterministic historical candles from the official Hyperliquid node fill archive without inventing missing microstructure.
- #252 added offline archive planning plus acknowledgement-gated requester-pays inspection/download with a hard byte budget and resumable integrity checks; no paid request is automatic.
- #253 composes a verified archive cache, public funding history, reconstructed candles, authenticated training data, and the existing model comparison into one paper-only archive experiment.
- #254 requires exact overlap reconciliation between archive-reconstructed and native Hyperliquid candles before archive-based model comparison may proceed.

The fixed shallow nonlinear tree challenger from #256 is merged behind the same four-block stability gate. It remains touched research and is not a promotion candidate unless a reproducible historical run demonstrates qualifying development-only edge.

Current economic conclusion: the system is correctly rejecting attractive-looking but unstable historical patterns. No merged historical learner has yet demonstrated repeatable cost-adjusted edge sufficient for promotion. The next priority is broader trustworthy history and reproducible challenger comparison, not weakening NO_TRADE or validation gates.



## Archive execution frontier — 2026-09-22

The deeper-history implementation is now ready for an **offline preflight + explicitly authorized local-cache run**. This section supersedes older archive-development text above where they conflict.

Merged execution/reproducibility hardening:

- #327 froze current-main preset `archive-jul-sep-2026-v2`: 2026-07-01 through 2026-09-20 23:55 UTC, 1,968 hourly fill-archive shards, BTC/ETH/HYPE/SOL, 5m+15m sources, 15m/1h/4h outcomes, fixed costs/thresholds/folds/tree geometry, four-block stability, and `touched_development` evidence only.
- #328 writes deterministic `preset-run.json`, binding the frozen preset to verified archive/source/overlap/dataset/comparison identities.
- #329 rejects reused or non-empty experiment output roots before the long run begins.
- #330 writes and verifies `preset-bundle.json`, digest-attesting canonical archive/source/dataset/comparison/receipt bytes.
- #332 writes `implementation.json`, hashing the exact installed `cocomelon` Python source tree before and after execution; a mid-run source change fails closed, and bundle schema v2 binds the implementation digest.
- #333 adds offline `cocomelon-historical-archive-preset preflight`, which verifies every local archive shard against the authenticated download manifest, requires the frozen 1,968-shard geometry, confirms a clean output root, fingerprints the exact implementation, and performs **no network/AWS/requester-pays action**.
- post-merge #333 CI run `35750670396` passed both the full test job and the research job on `a54c7ed8dc773b056135c51983a7f4351bb82057`.

Current archive execution rule:

1. Do **not** perform requester-pays inspection/download automatically. Archive acquisition remains acknowledgement-gated, byte-budgeted, and subject to separate explicit authorization.
2. When a complete authorized local cache exists, run the offline frozen-preset preflight first.
3. Proceed only if preflight verifies the archive manifest/shards, output-root cleanliness, and implementation identity.
4. Run the frozen preset in PAPER mode into that clean output root.
5. Verify `preset-run.json`, `implementation.json`, and `preset-bundle.json` before reading economic results.
6. Treat all resulting archive economics as TOUCHED / DEVELOPMENT-ONLY. Compare the transparent baselines, ridge family, portfolio-capacity variants, and the fixed shallow tree under the same chronological folds/costs/NO_TRADE/stability rules.
7. Do not tune from test outcomes. Freeze a new candidate only if reproducible touched evidence is strong enough to justify a separate future clean validation campaign.

The implementation blocker is closed. The remaining blocker for the multi-month archive experiment is an **explicitly authorized and verified local archive cache**; no paid transfer has been initiated by this development work.

**LIVE TRADING: DISABLED.**


## Prospective clean validation frontier — 2026-09-22

This section supersedes older "next action" text above wherever the two conflict.

Historical discovery has advanced to one frozen, prospective-only candidate:

- candidate: `hype-down-bearish-near-basket-long-4h-v1`;
- market: HYPE;
- frozen context: `down/bearish/near_basket`;
- direction: LONG;
- horizon: 4h;
- execution semantics: one position per market;
- modeled round-trip fee: `0.0007`;
- modeled round-trip slippage: `0.0005`;
- conservative funding reserve: `0.0001` per hour;
- source discovery remains TOUCHED / DEVELOPMENT-ONLY and cannot become clean evidence retroactively.

The clean prospective campaign is frozen before its first counted anchor:

- validation start: **2026-09-23 00:00:00 UTC**;
- first expected 1h anchor: **2026-09-23 00:59:59.999 UTC**;
- validation end: **2026-11-07 00:00:00 UTC**;
- finalization not before: **2026-11-07 04:00:00 UTC**;
- expected hourly anchors: **1,080**;
- minimum capture coverage: **90%**, therefore at least **972** observations and a maximum miss budget of **108** anchors;
- minimum settled executable trades: **80**;
- chronological stability blocks: **4**;
- minimum settled trades per block: **15**;
- required economics: overall modeled mean net return **> 0** and every block mean net return **> 0**;
- even a passing result becomes only **eligible_for_candidate_review**; it is not promotion or live authorization.

The clean campaign runtime is immutable:

- frozen observer/report/evidence source revision: `0131fccdb09a2b9ba959dd5785ea213a6297f719` (#299);
- #300 pins every scheduled/manual observer checkout to that exact revision and verifies it before execution;
- cumulative runtime attestation binds the candidate spec, frozen validation plan, and exact source revision;
- missing/conflicting runtime attestation after cutover fails closed.

The capture control plane is also frozen (#304):

- cron: `3,8,13 * * * *` UTC;
- frozen attempt minutes: 03, 08, 13;
- frozen maximum entry-candle age: 15 minutes;
- paper mode and canonical Hyperliquid mainnet endpoints only;
- cumulative state artifact: `prospective-hype-clean-state`;
- evidence root: `artifacts/prospective-hype-clean`;
- concurrency group: `prospective-hype-clean-observer`;
- `cancel-in-progress: false`;
- job timeout: 10 minutes;
- read-only contents/actions permissions;
- 90-day artifact retention;
- a pre-cutover `control-plane.json` attestation is required after cutover and is bound into lineage and finalization.

Evidence integrity is fail-closed:

- #296 requires restored cumulative state after cutover and rejects state resets;
- #297 stops new observations at the fixed validation boundary while allowing exact 4h settlements afterward;
- #298 publishes the frozen validation report and to-date capture health every cycle;
- #302 derives workflow-only recoverability without altering the frozen Python runtime, including remaining miss budget, maximum achievable final coverage, optimistic final settled-trade capacity, and block-level trade-count recoverability;
- if frozen requirements become mathematically unreachable, the workflow turns red only **after** state, lineage, report, and health artifacts are preserved;
- #303 predeclares exactly one canonical terminal `finalization.json`; it waits for all due exact-horizon settlements, freezes state/evidence/economics/runtime identity on the first eligible post-boundary cycle, and rejects later drift or conflicting finalization state.

Current development rule during the clean window:

1. **Do not retune or replace this candidate from prospective results.**
2. **Do not change its features, context definition, direction, horizon, costs, occupancy rule, validation thresholds, frozen Python runtime, or capture control plane.**
3. Continue unrelated engineering only if it cannot contaminate this campaign.
4. Treat health/lineage/finalization work as observational integrity, not strategy tuning.
5. At finalization, accept the predeclared verdict as-is. A failure remains a valid result.
6. A positive verdict is only candidate-review eligibility; all existing paper/shadow/risk/live gates remain mandatory.

**LIVE TRADING: DISABLED.**


## Pre-cutover operational verification — 2026-09-22

The frozen prospective campaign remains unchanged and has not started counting validation anchors yet. The independent audit/control layer was hardened and exercised against real GitHub Actions artifacts before cutover.

Verified operational frontier:

- PR #319 authenticated artifact producers across lineage, blind-monitor, and cutover audit paths without changing the frozen observer or strategy.
- PR #322 closed the remaining state-readiness provenance gap; post-merge CI and the state-readiness audit passed.
- PR #323 made blind-monitor state selection safe across legitimate GitHub Actions reruns, which reuse one workflow run ID while producing another cumulative state artifact. It also guarantees early redacted failure receipts can be written.
- PR #325 made lineage selection rerun-safe by comparing the latest cumulative states from the latest two **distinct observer workflow runs**, while taking the newest rerun artifact within each run; producer-provenance failures are now terminal after preserving redacted failure evidence.
- full post-merge CI for #323 passed in run `35737033904`;
- full post-merge CI for #325 passed in run `35740726772`; post-merge lineage audit `35740726978` and blind monitor `35740726702` both passed on first attempt;
- latest verified lineage artifact: `10699293253`, status `append_only_valid`, binding previous distinct-run state `10684992618` to current state `10697590747` rather than the older same-run rerun copy `10691392286`;
- the frozen clean observer was re-executed as run `35721665228`, attempt 2, and completed successfully without changing its frozen runtime/control-plane contract;
- the independent lineage audit was refreshed as run `35730889418`, attempt 2, and completed successfully;
- the synchronized blind monitor then passed as run `35737033996`, attempt 2;
- canonical successful blind-monitor artifact: `10697684067`;
- state artifact bound by that monitor: `10697590747`;
- monitor status: `pre_validation`;
- lineage status: `append_only_valid`;
- expected anchors to date: `0`;
- observations to date: `0`;
- missed anchors to date: `0`;
- overdue unsettled outcomes: `0`;
- irrecoverable reasons: none;
- interim economics remain redacted.

A prior post-merge monitor attempt failed closed first on stale health, then on lineage not yet covering the refreshed state. Those failures were valid operational vetoes, not strategy failures. After the frozen observer and independent lineage audit were refreshed in order, the monitor passed without weakening freshness, provenance, lineage, validation, or risk gates.

Current next action for this lane:

1. Keep the frozen observer, validation plan, candidate, costs, thresholds, schedule, endpoints, and control-plane attestation unchanged.
2. Allow the clean campaign to begin at the already frozen validation boundary on **2026-09-23 00:00:00 UTC**.
3. Keep independent readiness, lineage, blind-monitor, and cutover audits fail-closed.
4. Do not inspect or use interim economics for tuning during the clean window.
5. Treat any scheduler delay, stale source, provenance mismatch, lineage gap, or irrecoverable campaign-health result as an operational veto to resolve without weakening the frozen rules.
6. Keep live trading disabled; a future positive prospective verdict is only candidate-review eligibility and does not bypass paper/shadow/risk/live authorization gates.

**LIVE TRADING: DISABLED.**


## Prospective HYPE campaign frontier — 2026-09-23

The original D-027 V1 campaign remains immutable. No scheduled `prospective-hype-clean` observer run was created through its first declared post-cutover `:03/:08/:13` attempts after 2026-09-23 00:00 UTC. Pre-cutover repair PR #363 was closed unmerged after the boundary passed; V1 is not backfilled or rewritten.

PR #364 merged the fresh V2 primitives at `d15971eb22cec7b6fb2025bbb338c9d6d677eb63` after compile, Ruff, strict mypy, full pytest, and research CI passed. V2 keeps the same economic hypothesis and thresholds but has a new candidate/spec/plan/campaign identity and a fresh validation boundary at 2026-09-25 00:00 UTC.

The active integration task is the V2 control plane:

- pin observer runtime to `d15971eb22cec7b6fb2025bbb338c9d6d677eb63`;
- isolate V2 evidence at `artifacts/prospective-hype-v2-clean` and state artifact `prospective-hype-v2-clean-state`;
- use redundant off-peak schedule starts at UTC minutes 43/48/53;
- pre-warm scheduled runners toward the protected minute-03 hourly capture;
- preserve the 15-minute stale-anchor fail-closed ceiling;
- initialize runtime/control-plane/state attestations before the V2 cutover;
- preserve paper-only execution, canonical Hyperliquid mainnet endpoints, read-only permissions, non-cancelling serialized concurrency, and 90-day artifacts.

V2 validation remains research-only and non-promotional. Live trading remains disabled.

### V2 bootstrap verification — 2026-09-23

PR #365 merged as `d1b79504f9fbc1feacf32a3ce3164a8828871bfc`. Post-merge CI run `35802064960` passed, and the V2 workflow push-bootstrap run `35802064994` completed successfully before the 2026-09-25 cutover.

Verified bootstrap evidence:

- cumulative state artifact: `prospective-hype-v2-clean-state`, artifact `10726571181`;
- campaign ID: `72a465561e47cec5460d8ddf673a14e5ea6a9928b52a14f1fd8e467f747747e7`;
- candidate spec ID: `ae42874f608f6a6382b39a781a2f58b470612fff910905e7e88d9c9cb1d57def`;
- validation plan ID: `69975f885eb3a68163ab3ff465581f9829c6fedd6dac451900cc8eb7c18d77de`;
- runtime attestation ID: `492dc2b3fd06376d035983e8c71f55b3ded2213e43c4fadfbecba749964dfb4c`;
- control-plane ID: `078c5f15cb8e1151cf74f16e0d1c876ed05668b6b97f997512d1829990527a3d`;
- pinned observer revision: `d15971eb22cec7b6fb2025bbb338c9d6d677eb63`;
- bootstrap observations/outcomes: `0 / 0`;
- health: `pre_validation`;
- expected anchors: `1080`;
- remaining missed-anchor budget: `108`;
- maximum final capture coverage: `1`.

The exact next operational check is the first real scheduled V2 transport cycle: confirm that an off-peak `:43/:48/:53` schedule starts, pre-warms toward minute `:03`, restores artifact `10726571181` or its latest descendant, and republishes the same campaign/runtime/control-plane identities without creating a pre-cutover observation. After 2026-09-25 00:00 UTC, the first eligible hourly anchor is 2026-09-25 00:59:59.999 UTC and must be captured only through the frozen V2 transport; no backfill is allowed.


### Prospective HYPE V3 transport frontier — 2026-09-25

V2 remains immutable and continues to fail or recover under its frozen D-028 rules. Its scheduled run `36103594834` was created at 06:36 UTC and failed before evidence collection with `PREWARM_SCHEDULE_TOO_LATE_FOR_FRESH_CAPTURE`, confirming that delayed GitHub schedule creation can land outside the frozen freshness-safe phase.

V3 is now frozen for a new clean boundary at **2026-09-26 00:00:00 UTC**. The economic hypothesis and thresholds are unchanged from V2. The pinned V3 runtime revision is `298723c52d6a3b09839d05451d3d7db9753815bf`.

The V3 control-plane implementation under review removes `schedule` entirely and uses a bounded rolling `workflow_dispatch` queue:

- merge-push bootstrap seeds the next four UTC minute-03 capture targets;
- targets are created hours ahead rather than depending on schedule-event delivery;
- duplicate targets elect one deterministic leader before campaign state can be touched;
- each target releases the observer ten minutes before capture and the observer waits to the exact protected target when early;
- the unchanged 15-minute entry-candle freshness ceiling fails closed;
- each target replenishes only the next four missing targets, preventing recursive queue explosion;
- transient dispatch failures retry only GitHub 500/502/503/504 responses;
- queue visibility is re-verified before the transport step succeeds;
- transport receipts are non-economic and cannot become promotion evidence;
- V3 state is isolated at `artifacts/prospective-hype-v3-clean` / `prospective-hype-v3-clean-state`;
- execution is paper-only and live trading remains disabled.

The first expected V3 anchor is **2026-09-26 00:59:59.999 UTC**, intended for the pre-created **01:03 UTC** capture run. No V1/V2 evidence is copied into V3 and no missed anchor may be backfilled.


### Continuous outcome-learning frontier — 2026-09-25

A separate learning-evidence layer is being added without modifying the frozen V3 economics or producer workflow.

- settled V1/V2/V3 prospective outcomes can be harvested into an append-only learning ledger;
- V3 outcomes are quarantined from challenger research until the frozen campaign finalization boundary;
- future ordinary paper/live execution trades can preserve actual fees, funding, slippage, net PnL, and net-R with an explicit research-eligibility boundary;
- modeled prospective returns and realized execution PnL remain separate metric families;
- duplicate learning ingestion is idempotent and conflicting evidence fails closed;
- the running strategy is never self-retuned trade-by-trade; eligible evidence is used only to develop separately identified challengers.

This creates the feedback path for continuous improvement while preserving the validity of active paper/shadow tests. Live trading remains disabled.


### Leakage-safe learning dataset frontier — 2026-09-25

The outcome-learning ledger now has a deterministic dataset-snapshot layer:

- raw ledger records are never handed directly to challenger training;
- only records past their explicit research-eligibility boundary enter the training snapshot;
- quarantined records remain named in the manifest but are excluded from model inputs;
- prospective modeled-return, paper-execution, and live-execution evidence are separate partitions;
- the dataset ID binds the complete ledger digest and therefore changes even when new evidence is still quarantined;
- candidate IDs and exact record IDs remain auditable for future challenger lineage.

This is the next step toward continuous model improvement without leaking the running V3 test into its own successor research.

### Authenticated continuous-learning implementation frontier — 2026-09-25

The learning path is now end-to-end reproducible while remaining isolated from the frozen V3 campaign.

Merged implementation:

- #388 materializes immutable learning dataset bundles and authenticates eligible JSONL rows with SHA-256 lineage.
- #389 verifies bundle digests/record identities before reconstructing typed snapshots and freezes research-only challenger run manifests that bind exact input records, feature registry, model config, decision policy, and implementation revision.
- #390–#398 add target-isolated training sets, authenticated training bundles, grouped-mean and fixed-output research evaluation surfaces, plus atomic artifact persistence.
- #399 adds an authenticated point-in-time `FeatureSnapshot` store.
- #401 captures the exact decision-time feature snapshot used by trusted research replay and fails closed unless every decision fact has authenticated feature coverage.
- #402 lets frozen training registries consume authenticated numeric market features while rejecting missing stores, missing snapshots, market mismatches, or snapshots observed after trade open.
- #403/#404 add the fixed shallow nonlinear tree filter and reproducible CLI under chronological holdout, settled-before-cutoff training, explicit NO_TRADE thresholding, and per-block stability gates.
- #406 syncs authoritative paper/live execution journal outcomes into the append-only learning ledger with explicit candidate identity and research-eligibility timing while preserving realized fees, funding, slippage, net PnL, and net-R.
- #407 materializes a complete clean-root learning experiment: authenticated dataset -> frozen challenger run -> authenticated training bundle -> grouped-mean or fixed shallow-tree evaluation -> `experiment.json`. Its verifier re-authenticates child artifacts, lineage, evaluation identity, and research-only authority.
- #408 exposes that complete experiment verifier as a standalone audit command.

Current economic status:

- These merges establish trustworthy feature/outcome capture and reproducible challenger evaluation; they do **not** themselves demonstrate profitable edge.
- No continuous-learning challenger is promotion-eligible from implementation tests or touched research alone.
- Synthetic regression fixtures are engineering evidence only and must never be read as economic performance.
- V3 evidence remains quarantined from successor-challenger research until its frozen finalization boundary.
- Live trading remains disabled.

Next action for this lane:

1. Accumulate authenticated ordinary paper execution outcomes and settled prospective outcomes without changing the active producer.
2. Sync each source into the append-only ledger with its explicit research-eligibility boundary; never backdate eligibility.
3. Materialize a fresh authenticated dataset snapshot at an explicit `as_of_ms`.
4. Freeze challenger feature/model/policy/implementation identities before evaluation.
5. Run the reproducible experiment command on eligible evidence only, with grouped-mean as a transparent baseline and the fixed shallow tree as the nonlinear challenger.
6. Require positive overall and chronological-block results with adequate trade counts; otherwise NO_TRADE remains the decision.
7. Treat qualifying results as touched development evidence only. Freeze a separate candidate before any future clean validation campaign.

**LIVE TRADING: DISABLED.**

### Continuous-learning readiness gate — 2026-09-25

PR #410 implementation head `3fefce79ce13a5bb609e0b9e441ac03f8c274b76` passed CI run `36151628931`: the full test job and the research job both completed successfully, including compile, Ruff, strict mypy, full pytest, and the new readiness regressions.

The new `cocomelon-learning-readiness` surface is observational and research-only:

- freezes the evidence view at an explicit `as_of_ms`;
- separates eligible records from still-quarantined records for one evidence kind;
- reuses the exact training feature resolver instead of maintaining a weaker audit implementation;
- requires authenticated point-in-time feature coverage for every eligible record selected by the requested feature registry;
- reports valid-but-not-ready evidence separately from malformed/corrupt evidence;
- never trains, promotes, changes risk, mutates the frozen V3 campaign, or enables execution.

Next action for this lane:

1. Continue accumulating and syncing authenticated ordinary paper-execution outcomes and settled prospective outcomes under their existing eligibility boundaries.
2. Run the readiness audit against the real cumulative learning ledger and authenticated feature store at an explicit `as_of_ms`.
3. If zero eligible records or any required feature coverage is missing/late/mismatched, preserve the block and do not start challenger training.
4. When a selected evidence family is structurally ready, run the already-merged reproducible learning experiment with the transparent grouped-mean baseline and fixed shallow-tree challenger.
5. Treat any qualifying result as touched development evidence only; NO_TRADE remains the fallback and V3 remains quarantined until its frozen finalization boundary.

**LIVE TRADING: DISABLED.**

### Autonomous cumulative-learning operations — 2026-09-25

The research-only continuous-learning lane is now wired to real future campaign evidence without weakening active validation boundaries.

Merged implementation:

- #411 adds cumulative research-learning ingestion from successful required-candidate paper campaigns. It preserves only settled paper trades plus the authenticated decision-time feature snapshots those trades actually reference, binds ingestion to the exact upstream campaign revision/artifact lineage, and rejects legacy campaigns that predate authenticated feature capture instead of retrofitting them.
- #411 also adds `research-learning-evidence.yml`: successful main-branch research campaigns restore the latest trusted cumulative learning state, ingest new authenticated paper outcomes idempotently, run the fail-closed readiness audit, and republish `research-learning-state`.
- #412 adds `cocomelon-learning-cycle` plus `research-learning-cycle.yml`. The cycle is triggered only after a successful cumulative learning-state sync with newly created records.
- The frozen cycle requires at least **200 settled chronological training trades + 20 validation trades**, with **4 chronological stability blocks** and **5 validation trades per block** before any model experiment may run.
- The nonlinear challenger reuses the frozen historical archive tree settings: max leaf nodes `7`, min samples per leaf `100`, learning rate `0.05`, max iterations `100`, and L2 regularization `1`.
- The transparent grouped-mean baseline and fixed shallow tree remain separate research experiments; every child experiment is re-verified before the cycle can complete.
- A valid but undersized or structurally incomplete evidence set produces a persisted `not_ready` cycle receipt rather than lowering thresholds or starting training anyway.
- All cycle outputs remain `research_only=true`, `promotion_eligible=false`, and `execution_ready=false`.

Verification evidence:

- #411 exact implementation head `ebcd25ad58b642f2d45ff45c6ca12386eb561bde` passed CI run `36153241838` with both the full test job and research job green before merge `e432b6c51674ae4247cf1db05040ddeac78af2aa`.
- #412 exact implementation head `8e5311f375f49ac59f4e5e3fcae5b6fe9164dded` passed CI run `36155603300` with both the full test job and research job green before merge `069e2ca546a5c6b1261b2c0868ccd9e86a47f517`.

Current evidence boundary:

- The latest completed daily research campaign from 2026-09-25 was inspected and contains no `learning-features/` store. Its settled trades therefore remain outside the new authenticated learner; they are not backfilled or approximated.
- The existing daily research gap dispatcher already enforces at most one safe successful campaign per UTC day. The first future successful campaign produced with authenticated feature capture can become the first admissible cumulative-learning source.
- The frozen V3 prospective campaign remains isolated and quarantined from successor-challenger learning until its own finalization boundary.

Next action for this lane:

1. Let the existing daily research producer generate the next genuine mainnet paper campaign under its current one-per-day controls.
2. Require #411 ingestion to authenticate that campaign and copy only its trade-linked feature snapshots into cumulative learning state.
3. Let #412 emit `not_ready` until the 200/20 chronological capacity and both feature-readiness checks are satisfied.
4. Once the gate is genuinely satisfied, allow the automated research cycle to materialize and verify the transparent baseline plus fixed shallow-tree challenger.
5. Treat any `qualifies_development=true` result as touched development evidence only; freeze a separate candidate and future clean validation before any promotion decision.

**LIVE TRADING: DISABLED.**

### Continuous-learning recovery and operator visibility — 2026-09-25

The continuous-learning control plane now has bounded recovery for missed follower events and a provenance-safe operator surface.

Merged implementation:

- #414 adds authenticated `workflow_dispatch` recovery to both `research-learning-evidence.yml` and `research-learning-cycle.yml`. Recovery accepts only an upstream run ID; run attempt, head SHA, branch, repository, workflow path/name, event class, and successful conclusion are re-derived from GitHub before any artifact is admitted.
- #414 adds `research-learning-catchup.yml`, scheduled every ten minutes with activation boundary `2026-09-25T15:28:46Z` (the #411 cumulative-learning activation). It considers only the newest successful post-activation research campaign, repairs at most one missing stage per pass, refuses duplicate active followers, and therefore cannot sweep the pre-feature-store 2026-09-25 campaign into learning.
- Catch-up repairs evidence sync first and exits. A later pass may repair the autonomous cycle only after trusted cumulative state exists and only when the latest sync created new records. A zero-new-record sync intentionally does not create a cycle.
- #415 adds `cocomelon-learning-ops-status` and a strict non-economic learning-status renderer. It validates sync/readiness/cycle authority and digest continuity before rendering authenticated record/snapshot counts, eligibility/quarantine/blocker counts, structural readiness, and the frozen 200/20 chronological capacity.
- #415 integrates this section into the existing `Cocomelon Research Dashboard` issue. Learning status exposes no PnL, net-R, protected V3 interim observations, promotion authority, or execution authority.

Verification evidence:

- #414 exact implementation head `490e610aecf189a416b76477eb09093e6960e18f` passed CI run `36156844941` with both full test and research jobs green before merge `5c006044f93564e5b88f5db76e5b114cc32a7cdf`.
- #415 exact implementation head `a397b046252a3a6b58f18708503fdbb24f97a94f` passed CI run `36157475911` with both full test and research jobs green before merge `dd0e9582c175f3022ffad0635af40920b3f3073d`.
- The first real post-merge dashboard refresh, run `36157710812`, completed successfully on `main`. Issue #124 rendered the new learning section at 2026-09-25 15:58 UTC with the correct state: no authenticated post-activation continuous-learning state has been published yet, and pre-activation evidence is not backfilled.

Current operational chain:

`Research Daily Gap Dispatcher`
→ `Scheduled Research Mainnet Replay Campaign`
→ `Research Learning Evidence Sync`
→ `Research Autonomous Learning Cycle`

`Research Learning Catch-up` independently repairs a missing sync or cycle one stage at a time. The existing research dashboard refreshes after trusted learning producers and reports operational state without granting economic or execution authority.

Next action for this lane:

1. Preserve the one-safe-successful-research-campaign-per-UTC-day producer rule.
2. Admit only the first future campaign that carries authenticated decision-time feature snapshots and passes the #411 provenance checks.
3. Expect the learning cycle to remain `not_ready` until genuine settled chronological capacity reaches 200 train + 20 validation records.
4. Use catch-up only to repair missed control-plane followers; never use it to backfill pre-activation campaigns or weaken eligibility.
5. Keep all learning results touched/research-only until a separately frozen candidate passes a future clean validation protocol.

**LIVE TRADING: DISABLED.**



### Continuous-learning state continuity — 2026-09-25

PR #417 hardens cumulative research-learning state against long producer gaps without changing strategy economics or execution authority.

Merged implementation:

- #417 adds `research-learning-state-continuity.yml`, a daily research-only continuity checkpoint with manual recovery support.
- The checkpoint trusts only successful main-branch state artifacts produced by either `research-learning-evidence.yml` or the continuity workflow itself, with event-class, repository, branch, head-SHA, and workflow-path checks.
- Before republishing any state, it re-opens the append-only learning ledger and authenticated feature store, recomputes their state digests, verifies persisted record/snapshot counts, checks readiness count reconciliation, and reasserts `research_only=true`, `promotion_eligible=false`, and `execution_ready=false`.
- Normal scheduled refresh happens only when the newest trusted state is at least **14 days old**. Manual dispatch may force an earlier re-verification.
- Both newly synced cumulative state and continuity checkpoints now retain `research-learning-state` for **90 days**. The 14-day refresh window keeps a recoverable trusted checkpoint alive through prolonged periods with no admissible paper campaign while avoiding daily duplicate artifacts.
- Evidence sync, catch-up recovery, and the research dashboard now accept continuity-produced state only under the same explicit trusted-workflow checks.
- The dedicated research CI lane now includes the autonomous learning-cycle, learning-dashboard, and continuity workflow regressions in addition to the full-suite coverage.

Verification evidence:

- #417 exact head `99ecbcd16ba848bfa5dd739b9bc7a8a337205500` passed CI run `36160662153`; both the full test job and the expanded research job completed successfully before merge `06484be5754f27624e25fe26332bfeb3d7631d5a`.

Current evidence boundary:

- No new admissible post-activation paper campaign has appeared yet. The 2026-09-25 completed paper campaign still predates authenticated decision-time feature capture and remains outside continuous learning.
- The continuity workflow preserves already-authenticated cumulative state; it cannot invent evidence, backfill legacy trades, lower the frozen 200/20 capacity gate, train a challenger, promote a model, or enable orders.
- The next genuine successful research campaign with authenticated `learning-features/` remains the required source of the first continuous-learning records.

**LIVE TRADING: DISABLED.**


### Paper-producer learning evidence contract — 2026-09-25

PR #420 locks the scheduled paper producer to the authenticated learning-feature path required by continuous learning.

- The contract test binds `Scheduled Research Mainnet Replay Campaign` to trusted `complete_research_cohort(...)` completion.
- The trusted cohort implementation must continue materializing `output/learning-features`, reporting `feature_snapshot_count` and `feature_snapshot_state_digest`, and rejecting incomplete decision-to-feature coverage.
- `test_research_runner_workflow.py`, `test_research_cohort.py`, and the new producer-contract regression now run in the dedicated research CI lane as well as the full suite.
- #420 exact head `fedf35b862ddfb8a5bdcefc1f74bf15293e5623b` passed CI run `36161337393` with both full and research jobs green before merge `88322848be5287e0071d96d8d930fdea66499b0e`.

This is a producer integrity guard only. It does not change strategy logic, risk, sizing, promotion criteria, or execution authority.

**LIVE TRADING: DISABLED.**


### Continuous-learning state lineage — 2026-09-25

PR #422 makes cumulative research-learning state transitions independently auditable instead of trusting only the newest state digest.

Merged implementation:

- Each authenticated research-learning sync now appends an immutable lineage entry inside the cumulative state artifact.
- Every entry binds the exact upstream campaign run/attempt, head SHA, artifact ID/digest, required candidate identities, before/after learning-ledger counts and digests, before/after feature-store counts and digests, and created/existing evidence counts.
- Entries form a cryptographic predecessor chain with contiguous sequence numbers. Missing entries, tampering, broken predecessor links, state-tail mismatches, upstream run regression, or changed immutable artifact identity for the same run/attempt fail closed.
- The evidence sync verifies the existing chain before admitting a new campaign and writes the new transition only after evidence counts/digests reconcile.
- The 14-day continuity checkpoint now verifies the complete lineage and requires the latest sync receipt to match the lineage tail before republishing state.
- The autonomous learning cycle now re-opens the ledger and feature store, verifies their counts/digests, verifies the lineage tail, and refuses training if lineage does not match the sync receipt.
- The dedicated research CI lane includes the new lineage regressions.

Verification evidence:

- #422 exact head `596f66f6f8b09ae2520f095b41cae460bd510b1c` passed CI run `36162620181`; both full and research jobs completed successfully before merge `460549fc438176b799f3f8e8b2ef7f87bc5aa441`.

Current evidence boundary:

- No legacy paper trades are backfilled into this chain. The first lineage entry must come from a genuine post-activation campaign accepted by the authenticated learning sync.
- The chain adds provenance and rollback resistance only; it does not create evidence, relax the frozen 200/20 gate, alter strategy/risk, promote a challenger, or enable orders.
- The next admissible paper campaign with authenticated `learning-features/` remains the required source of the first continuous-learning records.

**LIVE TRADING: DISABLED.**

### Continuous-learning and paper-producer wakeups — 2026-09-25

PRs #424 and #425 reduce dependence on GitHub cron delivery without weakening evidence or execution boundaries.

Merged implementation:

- #424 makes `Research Learning Catch-up` wake on completion of either `Scheduled Research Mainnet Replay Campaign` or `Research Learning Evidence Sync`, while preserving its ten-minute schedule and manual recovery paths.
- Those `workflow_run` events are wakeups only: catch-up still re-discovers the newest successful post-activation campaign and latest trusted cumulative state from GitHub, authenticates them under the existing provenance rules, and repairs at most one missing stage per pass.
- #424 keeps duplicate-active-run checks and adds a short grace window so the normal follower can register before catch-up decides whether recovery is needed.
- #425 makes `Research Daily Gap Dispatcher` also wake when `Research V4 Acquisition Authority Sync` completes. The authority sync already runs shortly after UTC-day rollover, giving the paper producer an independent trusted wakeup if the dispatcher's own five-minute cron is delayed.
- #425 does not dispatch blindly: the existing active-V4, active-research, and successful-research-today checks remain unchanged, and the scheduled paper campaign itself still independently refuses a second successful cohort in the same UTC day.
- The daily-gap dispatcher contract now runs in the dedicated research CI shard as well as the full suite.

Verification evidence:

- #424 exact head `05e9085ae622e9637f6520f7e92a7ab88423eebb` passed CI run `36163232675` before merge `ab1fff95a624cbc88e70d86b510d1099a45995ed`.
- #425 exact head `cc445ac3878458487e8b24a0a5e2dd49499475e2` passed CI run `36168962249` with both full and research jobs green before merge `dd7e557b62e733f2f423d58221b326ca399a8263`.

Current evidence boundary:

- No new admissible post-activation paper campaign exists yet; the 2026-09-25 successful campaign still predates authenticated decision-time feature capture and is not backfilled.
- These wakeups improve control-plane reliability only. They do not create evidence, increase the one-successful-cohort-per-UTC-day cap, relax the frozen 200/20 learning gate, change strategy/risk/sizing, promote a challenger, or enable orders.
- The next genuine successful paper campaign produced with authenticated `learning-features/` remains the required source of the first cumulative-learning lineage entry.

**LIVE TRADING: DISABLED.**

### Learned-candidate clean-validation pipeline — 2026-09-25

PRs #427–#445 move continuous learning from authenticated development evidence through a complete, fail-closed, prospective clean-validation path while keeping live execution disabled.

#### CI control-plane efficiency

- #427 keeps CI on every pull request and on pushes to `main`, but stops duplicate feature-branch push CI.
- #428 adds per-PR/ref concurrency with `cancel-in-progress: true`, so superseded heads stop consuming Actions time while the newest head must still pass both the full and dedicated research jobs.
- The policy was exercised repeatedly during the clean-validation build: obsolete PR-head runs were cancelled while the latest head remained mandatory.

#### Leakage-safe development and immutable candidate freeze

- #429 adds deterministic chronological walk-forward partitions with explicit embargo/settlement checks for authenticated learning rows. This is a research utility and does not change the frozen autonomous 200-train / 20-validation capacity gate.
- #430 adds a canonical authenticated freeze for any development-qualified learning experiment. The freeze binds the exact experiment/data/training/evaluation identities and preserves the six-hour prospective embargo before clean validation.
- #431 fixes recovered autonomous-cycle artifact identity so manual catch-up uses the authenticated upstream sync run/attempt rather than absent `workflow_run` fields.
- #432 makes completed autonomous cycles freeze every independently qualified baseline/tree experiment. It does not rank them or select a winner.
- #433 packages a frozen candidate plus the exact known experiment artifact set into a self-contained, byte-hashed artifact that re-verifies even after the mutable development directory is removed.
- #434 exposes verified frozen candidate identity and validation-not-before timing operationally without exposing learner economics.

#### Frozen prospective clean protocol

- #435 freezes clean validation before evidence arrives: the first **20 settled candidate paper trades** after the embargo boundary, split chronologically into **four contiguous blocks of five**.
- Qualification requires overall mean realized net-R **strictly above zero** and every block mean realized net-R **strictly above zero**. The sample size, block structure, metric, threshold, candidate/package identity, and validation start are immutable.
- #436 reconstructs the frozen learner deterministically from its self-contained package, fitting only the same settled pre-validation training prefix used by the qualified development experiment. It supports the transparent grouped-mean family and the fixed shallow-tree family.
- #437 adds the append-only, spec-bound clean evidence store. It persists canonical predictions and one settled paper outcome per trade-eligible prediction, rejects outcomes for NO_TRADE predictions, reconciles candidate/spec/package/market/direction lineage, rejects reused source trades, and fails closed on tampering or unexpected files.
- #438 adds blind scoring. Before trade 20, the score exposes no mean-R, stability-block economics, or pass/fail. At trade 20, the first 20 settled outcomes, score timestamp, and selected-evidence digest freeze permanently; later trades cannot change that decision sample or score.

#### Autonomous admission and durable clean state

- #439 authenticates successful autonomous learning-cycle runs and admits every verified frozen development-qualified candidate into clean validation by packaging it and precommitting its validation spec.
- #440 bootstraps a 90-day durable clean-state lineage for each admitted candidate. Operational state is economically blind and reports only `waiting_for_validation_start`, `collecting`, or `ready_to_score` plus evidence counts.
- #441 exposes spec-bound prediction/outcome ingestion and verification without emitting prediction values, net-R, PnL, or clean pass/fail on the operator surface.
- #442 bridges authenticated scheduled paper campaigns into clean evidence. It reuses the existing campaign verifier, exact decision-time feature snapshots, and frozen candidate reconstruction; pre-boundary source trades are skipped, NO_TRADE predictions stay outcome-free, and accepted predictions can receive only their authenticated realized paper outcome.
- #443 adds the durable campaign follower. Every successful scheduled paper campaign can advance each trusted clean-state lineage, archive prior state receipts, persist a non-economic campaign-sync receipt, rebuild blind state at a stable campaign-completion boundary, and materialize the frozen score only once `ready_to_score`.
- #444 adds immutable terminal finalization. A verified complete score becomes either `eligible_for_candidate_review` or `validation_failed`; later follower passes re-verify the same finalization instead of rewriting it. **Candidate-review eligibility is not promotion authority and is not live readiness.**
- #445 closes the campaign-omission hole: clean-state ingestion now refuses a newer successful paper campaign while an earlier post-bootstrap successful campaign is missing. `Research Learning Clean Catch-up` checks every active trusted lineage, reauthenticates the globally oldest missing campaign and its exact artifact, avoids duplicate active followers, and repairs at most one gap per pass.

The resulting learning path is now:

`Scheduled paper campaign`
→ `authenticated cumulative learning evidence`
→ `autonomous development cycle`
→ `qualified candidate freeze`
→ `clean admission`
→ `durable clean-state bootstrap`
→ `contiguous authenticated paper-campaign sync`
→ `spec-bound clean predictions/outcomes`
→ `blind frozen first-20 score`
→ `immutable review-only finalization`.

#### Verification evidence

Every implementation PR in this sequence passed exact-head CI before merge:

| PR | Exact head | CI run | Merge |
| --- | --- | --- | --- |
| #427 | `954646d684345f0f8b1c9eb285616006546df4fa` | `36170262518` | `fab13839de3cf1c3027c6bdc8161d096f3ca5031` |
| #428 | `3258ef878ad19cc0671085ec2c58bf54229c344a` | `36170655247` | `90f63d7fc47ab411668cd7b423b50b4f3badcbf9` |
| #429 | `c96a5927f028b0349d8c0d4860d4e491752920fb` | `36170929221` | `3a333ea2ce24d60ccddc92326ee4f671f292775b` |
| #430 | `491055b08cb49dc811abb1c7c3ba78eb9b8a25d4` | `36171493862` | `f1669abe19dfe2d2a5ea03e98fbfb26a20107d0e` |
| #431 | `e5b1da83b11d534d1ca21d174dab0cb61e543b87` | `36171750161` | `100b78d91750a5a0e20ae8e887aa0fe518859f3c` |
| #432 | `4d0ddc6dc4c0b622887406f59655eab8e2c4f254` | `36172145753` | `617eb5e93ca4fb39f22835f27ca1db4c8c6bc4f3` |
| #433 | `e73c8ced4fee39af5b863398d5956df305f4fbcc` | `36172388846` | `f73781bdd3aa8d420fd02b5aad3f690f69133cb2` |
| #434 | `4e18c53c2d0c9474951ccf5f3ae632198b4118ea` | `36172643501` | `fb6c43c420a27198ce3d187da18d34fd43a950d1` |
| #435 | `cfc1a994c174bd0de41973625e3e7ebd7a594d7f` | `36172809951` | `5cd0eb0565fd8704e35ae42e8037375587a58ffc` |
| #436 | `3ea966ac39b8ab7b669bf7d311cfa70e4f36f73c` | `36173852933` | `6e809c116f3ced445efc9fd537ca93a8dcaeb9d2` |
| #437 | `be1ffd4430f83b20d91f1195899ddc9f0eca1778` | `36174482352` | `7079cfa46756693062af471a7f964f2dad538a21` |
| #438 | `c1f79f10734efb7017bce8763cc8b0f2ec816bd0` | `36175284890` | `86bd949575289372082517fe999639513a28c6ea` |
| #439 | `6b655e1c41190b1fc6d8720f004bf9ee5e06a64b` | `36175839617` | `c01c08940e12199412d5fce416f856d280f5f740` |
| #440 | `598b61da4e6fc93279ddb2eca2a600f5b49a68f7` | `36176660056` | `337f9f5cf7ea74d431aea6ed4c40a3b3af3999fd` |
| #441 | `3b3768152e7bf6df6dadb2b10e01eeddff16df3a` | `36177350098` | `34f2467a7e6713a57c3a5aca39f6e617c2943518` |
| #442 | `c0e16329b026901b9e3ff8bbcca5602c04e0ed7e` | `36185630347` | `646c7d6d4c9032f38347e2f494c9543bb723aa41` |
| #443 | `e311deb1b1558d1ca5e91660030b1c84f79980b6` | `36186495027` | `2a05e3e1dcd3d1fe5ab797168195671f4303d108` |
| #444 | `2a35ddae83a8143eabf063ca4672bcd73a4fa32c` | `36189397079` | `8461ead1871bff4103240316423e1cee4ff0db96` |
| #445 | `6de6bc3efe9dbb66c23a507ff6d8c8fb9a4ce9ba` | `36190467786` | `4f8fd7ef08a50750e057aa09c2b42dedca57cd07` |

Post-merge CI for #445 also passed on `main` in run `36190660934`.

#### Current evidence boundary

- A direct GitHub Actions check on 2026-09-25 still finds only one successful `Scheduled Research Mainnet Replay Campaign`: run `36075560252`, created at 00:01 UTC on pre-feature-store head `d200b2d4b3ea8d11ce6992fec2d121cf2a1c1b80`.
- That campaign is legacy touched paper evidence and is **not backfilled** into cumulative learning or learned clean validation.
- Therefore the continuous-learning and clean-validation machinery is operationally complete but still waiting for its first genuine post-activation campaign with authenticated `learning-features/`.
- No clean candidate can become review-eligible until real authenticated post-freeze paper evidence reaches the frozen 20-trade protocol.
- Even `eligible_for_candidate_review` is review-only. It does not satisfy the source-of-truth promotion gates, does not authorize Phase 10, and cannot enable orders.

**LIVE TRADING: DISABLED.**

### Learned clean-state durability and terminal review handoff — 2026-09-25

PRs #447–#451 harden the learned clean-validation lineage after campaign ingestion and add a terminal, authority-negative review handoff.

Merged implementation:

- #447 adds a daily clean-state continuity checkpoint with a 14-day freshness window and 90-day artifact retention. It re-verifies candidate package/spec/evidence/state, score/finalization, campaign receipts, state history, and generation lineage before republishing stale-but-valid state. Continuity creates no predictions, trades, scores, or economic evidence.
- #448 adds a verified non-economic review queue. The dashboard may surface lifecycle counts and terminal review-ready candidate identities, but it does not expose interim prediction values, PnL, net-R, rankings, promotion authority, or execution authority.
- #449 serializes clean-state campaign-follower and continuity writers under one non-cancelling concurrency group, preventing an older continuity snapshot from finishing after a newer campaign generation and becoming the apparent latest artifact.
- #450 adds an immutable terminal review dossier that can exist only after a verified `eligible_for_candidate_review` finalization. The dossier binds the exact frozen 20-trade sample, terminal score economics, package/spec/score/finalization identities, and selected outcome provenance.
- The #450 dossier explicitly records every current live-promotion requirement as `not_asserted_by_review_dossier`. It preserves `human_review_required=true`, `promotion_eligible=false`, and `execution_ready=false`.
- #451 materializes that dossier automatically inside durable clean state only for terminal review-ready candidates. Validation-failed candidates are forbidden from carrying a dossier, generation receipts bind dossier presence/identity, and continuity re-verifies the dossier before preserving state.
- The campaign follower remains economically blind: it gates dossier creation from the finalization reason-code invariant and does not expose the review verdict field or terminal economics in workflow summaries.

Verification evidence:

| PR | Exact head | CI run | Merge |
| --- | --- | --- | --- |
| #447 | `fba9726deae23b1faa8ac07b176338b1dd343cf5` | `36192454066` | `9558dfae3b8ae62fc709cebae923f44c4267de58` |
| #448 | `54ec46f2bd864e7f0310eb98e1385cd5daf169e9` | `36193569473` | `bf25f5fa0720f977ee55494a4ac4758fc35cb279` |
| #449 | `c32469b16b2b0cef3d4e38361526b8ad8b7325f4` | `36194020349` | `ec97f58e320d6e551017b875d866d9c9e6d4aa23` |
| #450 | `579d3f38c592f586225be3300d9fa82b2cd8a46c` | `36195380305` | `bb72d78fcf2a5449e149ec57c03415efd92193e6` |
| #451 | `82ae71c78389f0cb90fe631a88e0f07023446f1a` | `36195860998` | `dfeea1393b167d7fd8d61a4f3b04c199bf4929ed` |

Current evidence and promotion boundary:

- The only successful `Scheduled Research Mainnet Replay Campaign` on 2026-09-25 remains legacy run `36075560252`, produced before authenticated decision-time `learning-features/` capture and therefore not backfilled.
- Current HYPE V3 prospective workflow activity is a separate frozen evidence campaign and is not mixed into learned-candidate clean validation.
- A 20-trade clean pass can produce only `eligible_for_candidate_review` and a review dossier. It does **not** establish the live-promotion gates in `MASTER_SPEC.md`.
- Live promotion still requires at least 500 closed mainnet paper trades, at least 45 calendar days of shadow operation, positive cost-complete expectancy and untouched OOS evidence, walk-forward stability, profit factor >= 1.20, paper drawdown <= 8%, concentration/risk/recovery gates, and explicit user authorization with a capital amount.

**LIVE TRADING: DISABLED.**

### Current paper-trade status interpretation guardrail — 2026-09-26

The current paper trader is the **Continuous Mainnet Paper Trader**, not a Prospective HYPE experiment.

Paper evidence exists in separate families and must not be conflated:

- **active continuous ordinary paper runtime** — current simulated orders/fills/positions from the scanner -> strategy -> risk -> paper-execution stack;
- **scheduled research replay lanes** — touched/non-promotional research campaign evidence;
- **retired V4 corpus** — historical/touched development evidence;
- **retired Prospective HYPE V1/V2/V3** — historical research evidence only;
- **learned-candidate clean/shadow evidence** — a separate candidate-validation lifecycle.

Required current-state reporting rule:

- read GitHub Issue #469 (`Continuous Paper Trader — Live Status`) first;
- verify the newest active `Continuous Mainnet Paper Trader` run and its exact head SHA;
- use authenticated open-position/fill/journal state before claiming a trade opened or closed;
- treat Issue #82, Issue #124, retired HYPE artifacts, and old completed worker artifacts as historical context rather than current-position authority;
- if #469 lacks `Worker head SHA` and decision/risk diagnostics, it is a legacy #468 heartbeat: its `closed_trades` counter is unreliable and must not be quoted as a real trade count;
- the durable journal/artifact is authoritative for closed trades; #470 fixed the live unique-trade counter;
- workflow scheduling/dispatch is infrastructure continuity, not the economic decision cadence.

The active runtime continuously consumes mainnet market data for the deep shortlist, refreshes/ranks the broader native perp universe, evaluates the existing strategy on its 15-minute decision epochs, manages open positions on fresh market events, and remains paper-only.

Prospective HYPE D-029 remains historical documentation only and must not be restarted or presented as the current trader.

**LIVE TRADING: DISABLED.**

### Prospective HYPE experiment retired — 2026-09-26

By explicit user direction, all active Prospective HYPE V1/V2/V3 experiment workflows are retired.

Removed active orchestration includes:

- legacy Prospective HYPE clean observer scheduling;
- lineage/readiness/state-readiness/blind-monitor/cutover workflows;
- V2 clean observer and independent audit;
- V3 capture workflow, rolling dispatch queue, control heartbeat, cutover acceptance, and independent audit.

Historical artifacts and source modules that describe prior prospective research may remain for audit/reproducibility, but they are no longer an active producer and must not be reported as the current paper trader.

The intended paper-trading behavior is the canonical product behavior in `MASTER_SPEC.md`: continuously scan the eligible universe, rank opportunities, analyze the deep shortlist, emit LONG/SHORT/NO_TRADE, apply independent risk vetoes, and simulate approved orders against real Hyperliquid mainnet observations.

A separate long-running ordinary paper/shadow runtime is therefore the operational priority. The retired HYPE experiment must not be restarted merely to create trade activity.

This retirement changes experiment/control-plane authority only. Existing risk limits remain unchanged and live trading remains disabled.

**LIVE TRADING: DISABLED.**

### Continuous ordinary paper runtime — 2026-09-26

PR #464 replaces the retired periodic Prospective HYPE experiment as the operational paper-trading path.

The new runtime:

- scans/ranks the native Hyperliquid mainnet perp universe and keeps a dynamic deep shortlist;
- pins open positions even if their market falls out of the opportunity shortlist;
- consumes real mainnet L2, trades, active-asset context, and short-horizon candles continuously;
- runs the existing deterministic LONG/SHORT/NO_TRADE strategy stack on 15-minute decision epochs;
- preserves the existing independent risk engine and realistic paper IOC execution model;
- manages open positions from fresh market events rather than waiting for an hourly experiment anchor;
- persists paper execution, journal, evaluation facts, funding, open-trade lineage, mark extrema, and gap state for restart recovery;
- uses rolling 5.5-hour GitHub workers with exact predecessor-state handoff and a non-economic watchdog for continuity;
- refuses to start if execution mode is anything other than paper.

The runtime does not claim edge. Existing strategy quality remains what the evidence says; the purpose of this change is to observe/trade valid setups when they occur instead of missing them because of experiment cadence.

Live trading remains disabled. Existing risk and promotion gates are unchanged.

**LIVE TRADING: DISABLED.**

### Continuous paper legacy-heartbeat caveat — 2026-09-26

The first continuous worker launched from #468 (`073a016a62a79e53fe290cc39281beee0d156cae`) exposed a telemetry-only closed-trade counting defect: `BaselineReplayPipeline.finalize()` returns the cumulative completed-trade set, and the initial heartbeat counter added that full set again on every market event.

The durable journal did **not** duplicate those trades because `JournalStore.record_trade()` is idempotent on canonical `trade_id`. Therefore very large `closed_trades` values emitted by that legacy worker are not economic evidence and must not be quoted as real trade counts.

#470 (`641b2858f10f5aa041fd14548f4b087f7a978333`) corrected the runtime to track unique trade IDs and only journal newly completed trades. #473 added worker-SHA/predecessor lineage to live status. A heartbeat lacking those newer lineage/decision fields should be treated as legacy telemetry until the worker hands off.

Open-position/account telemetry from the legacy worker remains usable as point-in-time paper state when tied to its exact run, but closed-trade count must come from the corrected worker or durable journal/artifact.

### Continuous paper decision-time learning features — 2026-09-26

The ordinary continuous paper runtime now persists every evaluated decision-time `FeatureSnapshot` through the existing authenticated `LearningFeatureSnapshotStore` under its durable worker state.

This closes the provenance prerequisite for feeding actual continuous paper closures into the quarantined learning ledger:

- feature snapshots are recorded at the decision epoch before trade outcome is known;
- the store preserves canonical per-snapshot records and a deterministic state digest;
- the worker summary exposes snapshot count and state digest;
- the active strategy is not retuned from these records;
- downstream learning ingestion must still authenticate the completed worker artifact, exact journal trade, matching snapshot identity, and research-eligibility boundary.

This change creates evidence, not promotion authority. Live trading remains disabled.

**LIVE TRADING: DISABLED.**

### Continuous paper execution-to-learning attribution — 2026-09-26

PR #490 adds the missing provenance boundary between the ordinary continuous paper trader and the quarantined learning system.

The design records attribution at entry time:

- every new opening stores immutable opening-plan, feature-snapshot, market, opened-at, worker run/attempt, and worker-head-SHA lineage;
- worker identity is supplied directly from GitHub Actions (`GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_SHA`);
- the lineage store is append-only, canonical, digest-addressed, and part of the durable continuous-paper artifact;
- restored legacy positions remain compatible but are not retroactively attributed;
- completed trades without verified opening lineage are skipped from this learning path rather than guessed.

A separate `Continuous Paper Learning Evidence Sync` authenticates each successful worker and exact artifact, verifies the worker feature-store and opening-lineage counts/digests against its summary, then copies only attributed closed trades plus their exact decision-time features into a durable research-only learning state.

The evidence uses the existing `paper_execution` target family, preserving realized gross PnL, fees, funding, slippage, net PnL, and net-R. Each record remains bound to the opening worker SHA and run/attempt.

The continuous learning state is intentionally separate from the scheduled-research cumulative learning state for now. This avoids silently interleaving independent producer lineages before a dedicated merger/snapshot protocol is defined.

This changes evidence provenance only. It does not retune the active strategy, loosen risk, promote a candidate, or authorize live orders.

**LIVE TRADING: DISABLED.**

### Continuous paper isolated research cycle — 2026-09-26

The continuous-paper evidence path now has a dedicated research-cycle handoff while remaining separate from scheduled-research learning state.

The cycle:

- consumes only authenticated `continuous-paper-learning-state` artifacts;
- validates the exact upstream sync run, artifact digest, ledger count/digest, feature count/digest, readiness identity, and research-only authority;
- runs only when a sync created new attributed paper-execution records;
- reuses the frozen learning protocol requiring 200 settled chronological training records plus 20 validation records;
- publishes `not_ready` honestly before that capacity exists;
- may evaluate the existing grouped-mean and fixed shallow-tree research challengers once the capacity gate is met;
- does not automatically freeze, promote, shadow-admit, or execute any challenger.

The generic `cocomelon-learning-cycle` CLI is also registered as an installed package entry point, closing a latent packaging gap shared by the scheduled-research learning workflow.

Continuous-paper workers with decision-time feature capture but zero post-D-032 opening-lineage records are now reported as having no attributable openings rather than incorrectly described as pre-lineage workers.

**LIVE TRADING: DISABLED.**

### 5m versus 15m cadence shadow diagnostic — 2026-09-26

The continuous paper worker now carries a non-economic cadence comparator.

Purpose: measure whether the frozen V1 strategy surfaces useful additional opportunities when evaluated every 5 minutes instead of only on the production 15-minute decision clock, without changing execution authority.

The comparator:

- consumes the same authenticated ReplayRecords as the active continuous paper trader;
- runs independent 5-minute and 15-minute decision clocks through the unchanged feature/eligibility/strategy stack;
- never submits an order, never calls the risk engine for execution, never mutates positions, and cannot promote itself;
- records LONG/SHORT/NO_TRADE counts separately for each cadence;
- isolates 5-minute directional signals that occur off the normal 15-minute boundary;
- settles directional shadow observations only when an exact future 5-minute candle close exists at fixed 15-minute and 1-hour horizons;
- subtracts frozen research costs: 0.09% round-trip fee, 0.05% round-trip slippage, plus 0.01% funding reserve per hour;
- censors pending outcomes if a market leaves the deep shortlist rather than approximating across unavailable evidence;
- writes `cadence-shadow-summary.json` as the human/reporting snapshot and `cadence-shadow-state.json` as the restorable evidence checkpoint;
- restores deduplicated decision identities, still-pending horizons, settled outcomes, grouped counts, and diagnostic counters across continuous-paper worker handoffs;
- rejects incompatible horizon/cost/state schemas rather than silently mixing research protocols;
- fails open with respect to trading: a comparator or restore error starts a fresh diagnostic stream or disables the diagnostic without interrupting the ordinary paper trader.

Issue #469 may display this diagnostic live, including whether durable shadow state was restored for the current worker. Its 5-minute signals and forward outcomes are **not paper trades or PnL**. Current paper positions and closed trades remain the ordinary execution/journal fields.

Production execution remains on the existing 15-minute V1 strategy cadence. Durable shadow accumulation changes only research observability; no cadence or execution change is authorized by this diagnostic. Any later execution-cadence or entry-quality change requires enough cost-adjusted evidence to justify a separately validated decision.

**LIVE TRADING: DISABLED.**


### Continuous paper closed-trade path evidence — 2026-09-26

The continuous paper runtime now preserves exact intratrade mark sequences for future closed trades in a separate research-only sidecar.

- while a position is open, new authenticated mark observations are appended to a staged path at the existing 30-second runtime checkpoint boundary;
- staged open paths travel inside the same durable worker-state artifact, so a graceful worker rotation does not collapse the pre-handoff sequence to MFE/MAE extrema;
- when the position closes, staged marks are merged with the current worker's in-memory marks plus known gap intervals before the lifecycle is discarded;
- completed records are immutable, canonical, idempotent by trade ID, and conflicting rewrites fail closed inside the evidence store;
- the sidecar lives under `continuous-paper-state/trade-paths/`, so it follows the same 90-day worker-state handoff as the paper account;
- worker summaries expose completed path count, staged open-path count, completed-state digest, and any non-fatal capture error;
- trade-path capture failure cannot authorize orders or stop the paper trader; the runtime records the diagnostic failure and continues;
- the path sidecar does not alter `TradeJournalEntry`, execution accounting, strategy decisions, stops, sizing, or risk;
- evidence is prospective only. The first eight closed trades are not reconstructed from MFE/MAE because peak excursion does not reveal event order.

The purpose is to support honest counterfactual exit research such as fixed profit-lock or breakeven-stop rules using the actual observed path rather than inferring a path from MFE/MAE.

Operational verification immediately before this addition: continuous-paper worker #34 restored the durable cadence-shadow state from worker #31 with `state_restored=true` while preserving the open paper positions. The accumulated 5-minute off-cycle shadow sample was still research-only and did not modify production cadence.

**LIVE TRADING: DISABLED.**


### Fixed profit-lock mark-path counterfactual — 2026-09-26

The first exit challenger over continuous-paper path evidence is deliberately frozen before results are read.

Only two rules are admitted in this protocol:

- `breakeven_after_0_5r`: once exact mark-path favorable excursion first reaches +0.5R gross, arm a gross-breakeven mark stop at 0R;
- `lock_0_5r_after_1r`: once exact mark-path favorable excursion first reaches +1R gross, arm a mark stop that locks +0.5R gross.

There is no threshold grid, optimizer, adaptive tuning, or winner selection inside this study. These thresholds match the +0.5R and +1R excursion diagnostics already published by the live paper runtime before the challenger was implemented.

Counterfactual rules:

- only prospectively captured complete trade paths are evaluated; incomplete path evidence is skipped rather than repaired or guessed;
- path identity, market, direction, timestamps, entry/exit, quantity, stop, and initial risk must exactly match the durable journal or the study fails closed;
- activation and trigger order is resolved only from the authenticated mark sequence;
- when a candidate stop is crossed, the estimate uses the first observed crossing mark, not the ideal stop price, so mark gaps are not erased;
- triggered counterfactuals subtract the same frozen research cost reserve used by the cadence shadow: 0.09% round-trip fee, 0.05% round-trip slippage, plus 0.01% funding reserve per elapsed hour;
- if the candidate never triggers, the observed journal close is retained unchanged;
- outputs are research-only mark-based estimates, not executable fill claims, because the sidecar does not preserve the full L2 book required to reproduce a market-order fill at the counterfactual trigger.

This challenger has no execution authority and cannot change live paper stops, entries, exits, cadence, risk, or sizing.

**LIVE TRADING: DISABLED.**


### Profit-lock evidence readiness boundary — 2026-09-26

The fixed profit-lock counterfactual now has a precommitted evidence-volume gate that is intentionally separate from economic judgment.

A rule remains `collecting` until all of the following are observed prospectively:

- at least 30 complete exact trade paths evaluated;
- at least 15 trades on which that rule actually arms;
- at least 10 trades on which that armed rule actually triggers.

Only after all three counts are met may the rule become `ready_for_review`. This state means only that there is enough direct path exposure to inspect the economics without leaning on single-digit trigger counts.

The readiness gate does **not** inspect PnL direction, choose a winning rule, freeze a candidate, promote a stop policy, mutate the paper strategy, or grant execution authority. Even a rule with poor estimated economics can become ready for review once the evidence count is sufficient; promotion remains a separate prospective validation decision.

Current live evidence was still far below this boundary when the policy was frozen.

**LIVE TRADING: DISABLED.**


### Execution-aware profit-lock shadow — 2026-09-26

A stricter prospective exit-research layer now shadows the two frozen profit-lock rules against the same live L2 evidence and deterministic IOC simulator used by paper execution.

- the rules remain unchanged: breakeven after +0.5R and lock +0.5R after +1R;
- mark evidence arms and triggers each candidate, but candidate exits are simulated against actual subsequent visible L2 depth using the existing paper latency, slippage, size-quantum, notional, and taker-fee semantics;
- the shadow supports latency rejection, no-fill, and partial-fill continuation without mutating the authoritative paper account;
- simulated candidate economics use the actual journal entry fee, simulated exit fees, and the frozen funding reserve; they remain research estimates rather than claims about real executable venue fills;
- positions already open when the execution shadow first starts are excluded from execution-aware economic claims because their earlier L2 history was not captured by this observer;
- new positions are tracked prospectively end-to-end and the shadow state survives continuous-paper worker handoffs;
- a triggered candidate that cannot fully simulate its close before the actual paper trade closes is recorded as `triggered_incomplete` with no invented candidate PnL;
- state/config/rule mismatches fail closed inside the research layer, while runtime observer failures fail open with respect to the paper trader and disable only this shadow;
- Issue #469 reports eligible/excluded open positions, completed outcomes, IOC full closes, incomplete triggers, and per-rule estimated deltas;
- the existing 30 complete paths / 15 activations / 10 triggers readiness boundary remains a review gate only. This execution-aware layer does not weaken that boundary and cannot promote itself.

The authoritative paper strategy, current stops, 15-minute decision cadence, risk engine, fills, accounting, and live-order lock remain unchanged.

**LIVE TRADING: DISABLED.**


### Execution-shadow evidence readiness boundary — 2026-09-26

The visible-book profit-lock shadow now has a precommitted evidence-volume gate frozen before its first eligible trade outcome.

Each rule remains `collecting` until all four minimums are met prospectively:

- 30 economically evaluated eligible closed trades;
- 15 rule activations;
- 10 rule triggers;
- 10 fully simulated visible-book IOC closes.

Triggered candidates that cannot complete their simulated close before the actual paper trade ends remain explicit `triggered_incomplete` evidence and do not count toward the economically evaluated or full-IOC minimums.

Meeting these thresholds changes status only to `ready_for_review`. It does not grant promotion authority or execution authority, does not modify paper stops, and does not weaken the existing mark-path readiness boundary.

**LIVE TRADING: DISABLED.**


### Prospective LONG-trend entry filter study — 2026-09-27

A single entry-quality hypothesis is frozen prospectively before future outcomes are observed:

- candidate ID: `prospective-reject-long-trend-v1`;
- frozen rule: reject a paper trade only when its entry decision is `LONG` and its lead strategy is `trend`;
- all other directions and lead strategies remain admitted by the research candidate;
- the study begins at its durable `started_at_ms` and ignores earlier trades, including trades that were already open before the study started;
- the durable start state survives continuous-paper worker handoffs and cannot silently move after results appear;
- every prospective closed trade must match its persisted decision fact by market, direction, feature lineage, strategy-decision ID, and replay run;
- missing decision attribution prevents review readiness rather than being guessed or silently dropped.

The reported economic delta is intentionally limited to **closed-trade contribution**: blocked trades contribute zero and allowed trades retain their observed paper net PnL. It is not a portfolio counterfactual because skipping a trade can alter later risk capacity, cooldowns, position concurrency, and replacement opportunities.

The study remains `collecting` until all three volume gates are satisfied prospectively:

- 30 prospective closed trades;
- 10 blocked LONG+trend trades;
- 10 allowed trades;
- zero attribution misses.

Meeting the evidence gate means only `ready_for_review`. It grants no execution or promotion authority and cannot mutate the paper strategy.

**LIVE TRADING: DISABLED.**


### Prospective opening scanner-rank attribution — 2026-09-27

The continuous paper runtime now records the market's latest **coarse universe rank observed before each new opening**.

- rank evidence is prospective only; historical trades are not backfilled;
- every record is bound to the paper opening plan, market, opening timestamp, rank observation timestamp, ordinal, score, rank-pool size, and scanner reason codes;
- the runtime refuses to use a rank observation timestamped after the opening, so the attribution cannot leak future information;
- the rank tracker refreshes from the same periodic native-market snapshot already fetched by the paper worker and does not add a new market-data dependency;
- records are immutable, canonical, conflict-detecting, and travel in the ordinary durable paper-state artifact;
- Issue #469 attributes closed paper PnL and mean R into rank buckets `1-5`, `6-10`, `11-20`, and `21+`, while separately reporting record age;
- older closed trades without prospective rank records are labeled as such rather than treated as capture failures.

This diagnostic does not change the deep-watch shortlist, scanner weights, strategy decisions, risk, sizing, stops, or execution. It exists to determine whether losses are concentrated in lower-ranked opportunities before any selection rule is changed.

**LIVE TRADING: DISABLED.**


### Exact-path post-entry markout diagnostic — 2026-09-27

The continuous paper runtime now measures signed post-entry markout at fixed 1-minute, 5-minute, and 15-minute horizons from the actual paper entry price.

- each horizon uses the first observed exact-path mark at or after that fixed timestamp;
- markout sign is normalized by trade direction, so positive means favorable for both LONG and SHORT;
- outputs include mean signed basis points, gross R, positive/negative counts, and observation lag;
- results are split by side and persisted lead strategy;
- trades that close before a horizon are censored rather than assigned an invented price;
- incomplete trade paths and missing observed marks are reported explicitly;
- decision lineage mismatches fail the diagnostic, while runtime publication failure remains fail-open for the paper trader.

This is a measurement layer only. It does not delay entries, reject trades, modify scanner ranking, alter stops, or grant promotion/execution authority.

**LIVE TRADING: DISABLED.**


### Entry-markout evidence readiness boundary — 2026-09-27

The 1m / 5m / 15m post-entry markout diagnostic now has a precommitted sample-volume gate frozen before its first live results were reviewed.

Each fixed horizon remains `collecting` until it has at least 30 actual observed markouts. Trades that close before a horizon are censored and do not count toward that horizon; missing marks are not imputed.

The gate is deliberately economic-blind: positive and negative markouts count equally. Reaching 30 observations changes only that horizon to `ready_for_review`. All three horizons must independently reach 30 before the diagnostic is labeled fully ready for review.

This readiness state does not choose an entry-delay rule, reject trades, change strategy thresholds, promote a candidate, or grant execution authority.

**LIVE TRADING: DISABLED.**


### Entry markout freshness bound — 2026-09-27

The exact-path entry markout diagnostic now accepts a horizon observation only when the first available mark at or after the target arrives within 60 seconds of that target.

- the fixed horizons remain 1 minute, 5 minutes, and 15 minutes after the actual paper entry;
- marks arriving more than 60 seconds after the requested horizon are classified as `stale_observed_mark` and excluded from markout economics;
- stale marks do not count toward the 30-observation-per-horizon readiness gate;
- trades closed before a horizon remain censored;
- trades with no later mark remain missing;
- no interpolation or backfilling is allowed;
- Issue #469 reports the freshness bound and stale count separately for each horizon.

This corrects a measurement-quality problem where a much later mark could previously be labeled as a 1m/5m/15m markout. It changes research telemetry only and does not change paper entries, exits, risk, sizing, cadence, or live-order controls.

**LIVE TRADING: DISABLED.**


### Prospective allMids entry markout shadow — 2026-09-27

A denser research-only entry-timing observer now measures public mid-price movement after new continuous-paper fills using the already-subscribed Hyperliquid `allMids` stream.

- the fixed horizons are frozen at 1 minute, 5 minutes, and 15 minutes after the actual paper opening time;
- only the first allMids observation at or after each horizon is considered;
- an observation is usable only when it arrives within 60 seconds of the target; later first observations are labeled `stale`;
- LONG and SHORT movement is direction-normalized into signed basis points and gross R;
- trades closed before a horizon are censored; horizons reached without an observed mid before close are labeled `missing_at_close`;
- no interpolation, backfill, or invented price is allowed;
- positions already open when this observer first deploys are excluded from prospective claims;
- state persists across continuous-paper worker handoffs, including partially observed open positions;
- persisted decision facts attribute fresh observations by lead strategy without changing those decisions;
- runtime failures disable only this observer and remain fail-open for the paper trader.

This shadow uses public midpoint observations. It is not a mark-price claim, an executable fill simulation, an entry filter, or promotion evidence. The authoritative strategy, scanner, risk engine, paper execution, stops, accounting, and live-order lock remain unchanged.

**LIVE TRADING: DISABLED.**


### allMids markout evidence-quality readiness boundary — 2026-09-27

The prospective allMids 1m / 5m / 15m entry markout shadow now has a frozen evidence-quality gate before any timing rule can be reviewed.

Each horizon remains `collecting` until all of the following are true:

- at least 30 fresh allMids observations exist at that horizon;
- among trades that reached the horizon, the combined stale + missing-at-close fraction is at most 10%;
- decision-fact attribution misses are zero.

The shadow as a whole is `ready_for_review` only when all three horizons meet those conditions and unmatched closed trades are zero. Trades that close before a horizon remain censored and do not count against coverage quality.

This gate is deliberately economic-blind: positive and negative markouts count equally. Reaching the gate grants neither promotion authority nor execution authority and does not choose an entry delay, reject trades, change scanner ranking, or alter paper execution.

**LIVE TRADING: DISABLED.**


### Prospective top-10 scanner-rank filter study — 2026-09-27

A single scanner-selection hypothesis is frozen prospectively before future outcomes are reviewed:

- candidate ID: `prospective-admit-top10-rank-v1`;
- admit only openings whose latest coarse scanner rank is 1–10;
- shadow-reject openings ranked 11 or worse;
- use only rank evidence observed at or before the actual paper opening and no older than 5 minutes;
- start from a durable timestamp after this candidate is deployed, so earlier rank-11–20 losses do not count as proof;
- missing or stale rank evidence prevents review readiness rather than being guessed.

The reported delta is **closed-trade contribution only**. A blocked trade contributes zero while allowed trades retain their observed paper PnL. This is not a portfolio counterfactual because skipping an opening can change later risk capacity, cooldowns, concurrency, and replacement opportunities.

The study remains `collecting` until it has at least 30 prospective closed trades, including at least 10 allowed top-10 trades and 10 blocked rank-11+ trades, with zero missing or stale rank evidence.

Reaching the gate means only `ready_for_review`. The candidate has no promotion authority and no execution authority and cannot change the live paper shortlist or entry decision.

**LIVE TRADING: DISABLED.**


### Entry markout attribution by scanner rank — 2026-09-27

The exact-path 1m / 5m / 15m post-entry markout diagnostic now also attributes fresh observations by the scanner rank recorded at the actual paper opening.

- rank buckets are `1-5`, `6-10`, `11-20`, and `21+`;
- rank evidence must match the opening plan, market, and opening timestamp exactly;
- rank evidence older than 5 minutes is labeled `stale` rather than assigned to a fresh bucket;
- missing rank evidence is labeled `unknown` rather than dropped;
- missing/stale rank-attribution counts and rank-age statistics are published beside the horizon markouts;
- this lets the research layer distinguish immediate adverse selection in lower-ranked markets from later lifecycle/exit giveback.

This is measurement only. It does not change scanner ranking, shortlist membership, entries, stops, risk, sizing, cadence, or execution authority.

**LIVE TRADING: DISABLED.**


### Closed-trade execution-friction attribution — 2026-09-27

The continuous paper live status now decomposes each closed trade into an exact accounting waterfall:

`reference-price gross - signed slippage = actual gross; actual gross - fees + funding = net PnL`.

- reference-price gross adds the journal's signed entry/exit slippage back to actual realized gross;
- positive signed slippage is adverse execution drag and negative signed slippage is favorable execution;
- fees and funding are kept separate from slippage so costs are not double-counted;
- the diagnostic reports adverse/favorable slippage amounts, fee drag, funding contribution, net cost drag, and mean-R equivalents;
- it counts trades that were positive before execution friction but non-positive after it, plus trades rescued by favorable friction;
- the same decomposition is reported by side and persisted lead strategy;
- decision-fact lineage mismatches fail the research diagnostic, while heartbeat publication remains fail-open for paper trading.

This is attribution only. It does not alter strategy thresholds, scanner ranking, entries, exits, stops, sizing, cadence, risk, or execution authority.

**LIVE TRADING: DISABLED.**


### Account lifecycle realized-economics bridge — 2026-09-27

The continuous paper live status now separates account cash already realized inside still-open positions from economics belonging to fully closed journal trades.

- each open paper position already carries cumulative realized gross PnL, fees, and funding from partial/reduce-only execution plus funding accruals;
- the bridge computes open-lifecycle realized net cash as `realized gross - fees + funding`, then adds current unrealized PnL for mark-to-market lifecycle contribution;
- subtracting those open-lifecycle cumulative amounts from account-wide realized gross, fees, and funding yields the account-implied fully closed lifecycle economics;
- those implied closed totals are compared directly with the durable trade journal;
- the bridge also verifies `starting cash + realized net cash = cash` and reconciles total account PnL as `closed journal net + open-lifecycle realized net + open unrealized`;
- all gross/fee/funding/net and equity reconciliation deltas are published explicitly instead of silently assuming that account realized PnL came only from completed trades;
- a mismatch disables only this diagnostic and never changes paper execution authority.

This resolves the ambiguity where partial reductions can increase account realized gross PnL while the closed-trade count remains unchanged.

**LIVE TRADING: DISABLED.**


### Entry decision age at fill diagnostic — 2026-09-27

The continuous paper runtime now measures how old the persisted strategy decision is when the first actual opening fill occurs.

- the authoritative decision timestamp comes from the stored decision fact;
- the authoritative opening timestamp is the first opening fill timestamp used by the trade journal assembler;
- impossible time regressions fail the research diagnostic rather than being normalized;
- fixed descriptive bands are `<1s`, `1-<5s`, `5-<15s`, `15-<30s`, `30-<60s`, and `60s+`;
- outcomes are summarized by age band, side, and lead strategy, plus mean/median/p90/max decision age;
- review remains `collecting` until at least 30 attributed closed trades with zero attribution misses;
- this diagnostic does not delay entries, reject stale decisions, change execution latency, or grant promotion/execution authority.

**LIVE TRADING: DISABLED.**


### Research lineage mismatch containment — 2026-09-27

Research-only position observers now contain close-lineage mismatches instead of disabling their entire evidence stream.

- profit-lock execution shadow and prospective allMids markout shadow still require exact close lineage for a trade to contribute economics;
- a mismatched close is excluded from that study and increments a durable `lineage_mismatch_closed_trades` counter;
- restored research positions no longer present in the authoritative paper account are dropped at worker startup and counted as `orphaned_restored_positions`;
- these counters survive worker handoffs and block `ready_for_review` until they are zero;
- no mismatched trade is repaired, reconstructed, or allowed into research economics;
- the authoritative paper account, journal, fills, risk, stops, and execution behavior are unchanged.

This lets a single research-lineage discrepancy remain visible without permanently disabling future evidence collection.

**LIVE TRADING: DISABLED.**


### Entry markout attribution by decision age — 2026-09-27

The exact-path 1m / 5m / 15m post-entry markout diagnostic now also groups fresh observations by the age of the persisted strategy decision at the actual opening fill.

- the age source is the same authenticated decision fact used by the standalone decision-age diagnostic;
- the buckets are the same fixed bands: `<1s`, `1-<5s`, `5-<15s`, `15-<30s`, `30-<60s`, and `60s+`;
- impossible cases where the fill precedes the decision fail the research diagnostic rather than being normalized;
- missing decision facts remain explicitly unattributed;
- this lets the paper evidence distinguish immediate adverse selection associated with older decisions from adverse selection associated with side, strategy family, or scanner rank.

This is attribution only. It does not delay, reject, or reprioritize entries and has no promotion or execution authority.

**LIVE TRADING: DISABLED.**


### Live research readiness board — 2026-09-27

Issue #469 now includes one compact board that summarizes the frozen evidence gates for the active paper-trading research studies.

- each study is shown as `collecting`, `review-ready`, `error`, or `disabled`;
- the board surfaces current evidence counts plus data-integrity counters such as missing attribution, lineage mismatches, orphaned restored state, and stale rank evidence;
- the current board covers fixed profit-lock, visible-book IOC profit-lock, LONG+trend filter, top-10 rank filter, exact-path entry markouts, allMids entry markouts, and decision age at fill;
- `review-ready` means only that the study's precommitted evidence gate is satisfied;
- the board has no promotion or execution authority and cannot change paper behavior.

This is intended to keep operational status and future-chat interpretation aligned with the actual evidence gates instead of treating small samples as strategy decisions.

**LIVE TRADING: DISABLED.**


### Fixed 60-second delayed-entry execution shadow — 2026-09-27

A single prospective entry-timing challenger is frozen before its future results are observed.

- candidate: wait exactly 60 seconds after the actual paper opening timestamp, then attempt the same opening size once against the first fresh eligible L2 book;
- the delayed shadow keeps the original paper stop and planned-risk ceiling and uses the same paper IOC latency, slippage, fee, size-quantum, visible-depth, and risk-envelope rules;
- the observation window is capped at 60 seconds after the delayed target. If no usable book arrives inside that window, the attempt is recorded as expired/missing rather than assigned an invented price;
- full delayed fills are compared with the actual paper entry using direction-normalized price improvement in basis points and gross R;
- partial fills, no-fills, execution rejections, trades closed before the delayed target, and missing delayed books remain separate evidence classes and are never promoted into a full-fill comparison;
- positions already open before the shadow begins are excluded prospectively;
- shadow state survives continuous-paper worker handoffs and reconciles restored positions against the authoritative paper account;
- lineage mismatches and orphaned restored positions block research readiness instead of being repaired silently.

The review gate is frozen at 30 prospective eligible closed trades and 20 full delayed IOC fills, with zero unresolved lineage/orphan integrity failures. Reaching that gate grants review readiness only.

This study has no execution or promotion authority. It does not delay the real paper entry, alter position size, change stops/risk, or submit an order.

**LIVE TRADING: DISABLED.**


### Delayed-entry original-stop lineage hardening — 2026-09-27

The fixed 60-second delayed-entry shadow now resolves its stop from the immutable persisted opening `PaperOrderPlan`, not from the mutable current `PaperPosition.stop_price`.

- a later profit-protection/tightening action cannot rewrite the delayed-entry candidate's original risk geometry;
- the opening plan must exist, be non-reduce-only, match the position market, and contain a stop;
- any lineage failure disables only the research shadow and remains visible as a research error;
- the delayed-entry state schema is bumped to v2, so any v1 state is rejected and restarted prospectively rather than mixed into the corrected protocol.

This changes research integrity only. It does not modify the authoritative paper stop or any order behavior.

**LIVE TRADING: DISABLED.**


### Closed-trade outlier robustness sensitivity — 2026-09-27

The continuous-paper live status now includes a deterministic sensitivity check for winner concentration.

- it reports the largest realized winner and the top-one/top-two shares of gross profit;
- it recomputes net PnL, mean/median net R, and profit factor after removing the single best winner and the two best winners from the same closed-trade sample;
- it explicitly reports whether positive net PnL survives those removals;
- it does not invent replacement trades, alter chronology, resample outcomes, or claim a portfolio counterfactual;
- review readiness remains `collecting` until at least 30 closed paper trades.

This diagnostic has no execution or promotion authority. Its purpose is to prevent a small number of outlier winners from being mistaken for a durable edge.

**LIVE TRADING: DISABLED.**


### Continuous-paper drawdown / high-water telemetry — 2026-09-27

The continuous-paper runtime now maintains two separate drawdown views.

- sampled account drawdown observes full paper equity, including unrealized PnL, whenever the existing durable runtime checkpoint is actually persisted;
- the configured checkpoint interval and the observed mean sample interval are both surfaced because runtime scheduling can make the realized sample cadence coarser;
- the sampled high-water state survives worker handoffs and preserves first/latest/peak equity plus maximum drawdown peak and trough;
- corrupt or incompatible drawdown state restarts only the research diagnostic and cannot interrupt the paper trader;
- realized closed-trade drawdown is recomputed exactly from starting cash plus chronological closed-trade net PnL;
- the live status keeps sampled mark-to-market drawdown and realized closed-trade drawdown separate because they answer different questions;
- sampled account drawdown may miss extremes that occur between actual observations, and the live status states that limitation explicitly.

This is observability only. It has no execution or promotion authority and does not change risk limits, sizing, stops, entries, exits, or cadence.

**LIVE TRADING: DISABLED.**


### Exact-path excursion timing diagnostic — 2026-09-27

The continuous paper research layer now measures when favorable and adverse excursion happens, not only how large the eventual MFE/MAE becomes.

- only completed exact trade paths with complete MFE/MAE evidence are evaluated;
- first-hit timing is frozen at +0.25R, +0.5R, and +1R gross favorable excursion;
- the diagnostic reports mean/median first-hit time, how many trades later closed negative after each threshold, and the mean remaining time from threshold hit to those losing closes;
- it reports time-to-MFE, time-to-MAE, peak-to-close duration, and the fraction of the total holding period spent after peak favorable excursion;
- the same timing summaries are split by side, persisted lead strategy, and actual exit reason;
- path/journal identity mismatches fail the diagnostic instead of being guessed;
- missing decision or excursion attribution blocks review readiness;
- the frozen review gate is 30 complete exact paths with clean attribution.

This is observability only. It does not move stops, delay entries, force exits, change strategy thresholds, or grant promotion/execution authority.

**LIVE TRADING: DISABLED.**


### Closed-trade chronological stability diagnostic — 2026-09-27

The continuous paper runtime now measures whether realized net economics persist through time rather than relying on one aggregate result.

- closed trades are ordered deterministically by close time;
- overlapping rolling 5-trade and 10-trade windows report the latest net PnL / mean net R, the fraction of positive windows, and best/worst window economics;
- the full chronological sample is split into four deterministic blocks;
- each block reports wins/losses, net PnL, mean net R, and profit factor;
- the frozen review gate requires 40 closed trades so all four chronological blocks contain at least 10 trades;
- review telemetry separately reports whether every full block has positive net PnL and positive mean net R;
- the gate is evidence readiness only. It does not promote a strategy or change execution.

This complements the outlier-robustness test: robustness asks whether one winner dominates aggregate PnL, while chronological stability asks whether economics repeat across time.

**LIVE TRADING: DISABLED.**


### Closed-trade concentration diagnostic — 2026-09-27

The continuous-paper live status now reports whether realized positive economics are concentrated in a small number of markets or time buckets.

- concentration uses the exact Phase 9 definition: first net PnL inside each group, keep only groups whose net PnL is positive, then divide each positive group by the sum of all positive groups;
- market, persisted lead-strategy, and UTC fixed seven-day buckets are reported with trade count, W/L/BE, net PnL, mean net R, trade-count share, and positive-net-PnL share;
- the report includes trade-count HHI and positive-PnL HHI so both sample concentration and economic concentration are visible;
- the largest positive contributor is surfaced for market, lead strategy, and seven-day bucket;
- the existing later-live reference limits are shown without granting authority: no single market above 35% of total positive grouped net PnL and no single seven-day bucket above 50%;
- when there is no positive group, the positive-contributor/share fields remain unavailable rather than choosing an arbitrary zero-PnL group;
- lead-strategy grouping uses immutable decision facts and reports attribution misses;
- any concentration calculation failure disables only this research diagnostic and cannot interrupt paper execution.

This is observability only. It does not block markets, modify scanner ranking, change risk, alter entries/exits, or authorize promotion.

**LIVE TRADING: DISABLED.**


### Closed-trade UTC decision-hour diagnostic — 2026-09-27

The continuous-paper live status now attributes realized closed-trade economics to the UTC hour of the immutable strategy decision.

- the hour is derived from the persisted strategy-decision timestamp, not from opening fill or close time;
- only trades with exact decision-fact lineage are attributed; missing decision facts remain explicit misses;
- occupied UTC hours report trade count, W/L/BE, net PnL, mean net R, win rate, profit factor, and trade-count share;
- the report also exposes the number of active/positive/negative UTC hours and trade-count HHI across active hours;
- the grouping is fixed to the 24 UTC clock hours and is not fitted from outcomes;
- evaluation failure disables only this research diagnostic and cannot interrupt paper execution.

This completes the Phase 9 deterministic live slice for UTC hour. It is observability only and does not suppress, delay, reprioritize, size, or promote trades.

**LIVE TRADING: DISABLED.**


### Whole-market robustness sensitivity — 2026-09-27

The existing closed-trade robustness diagnostic now tests whether aggregate paper profitability survives removing every trade from the single highest positive-net-PnL market.

- markets are grouped by realized net PnL across the same closed-trade sample;
- only markets with positive grouped net PnL can become the removed market;
- the report exposes the top positive market, its grouped net PnL, trade count, and share of total positive market-level PnL;
- it then removes every closed trade from that market and recomputes remaining trade count, net PnL, mean/median net R, profit factor, and whether net PnL remains positive;
- when no market has positive grouped net PnL, no market is selected and the scenario removes nothing;
- this is deterministic sensitivity over the realized sample, not a claim that the removed market would have been replaced by other trades.

The purpose is to detect whole-market dependence that single-best-trade sensitivity can miss. It cannot block a market or change scanner ranking, risk, sizing, entries, or exits.

**LIVE TRADING: DISABLED.**


### Entry markout → final outcome diagnostic — 2026-09-27

The continuous-paper research layer now measures whether early post-entry markout direction predicts the eventual closed-trade result.

- the diagnostic reuses the same exact-path 1-minute, 5-minute, and 15-minute markout definition and 60-second maximum observation lag;
- each usable horizon observation is frozen into favorable, adverse, or flat based only on signed gross R at that horizon;
- favorable and adverse groups report eventual W/L/BE, win rate, realized net PnL, and mean final net R;
- sign accuracy counts favorable-then-winning plus adverse-then-losing outcomes over non-flat observations;
- short-lived trades are censored and stale/missing marks are excluded rather than imputed;
- the review gate is fixed at 30 usable observations per horizon, including at least 10 favorable and 10 adverse observations;
- reaching the evidence gate grants review readiness only and cannot create an entry filter, early-exit rule, or execution change.

The purpose is to determine whether immediate adverse selection has genuine predictive value before any timing rule is proposed.

**LIVE TRADING: DISABLED.**


### Exact opening fill-liquidity diagnostic — 2026-09-27

The continuous-paper runtime now captures the exact L2 book consumed by each future opening IOC after the authoritative paper attempt has already been computed.

- evidence is prospective only; historical trades are not reconstructed from decision-time feature snapshots;
- each filled opening records spread, bid/ask visible notional within 25 bps, direction-adjusted imbalance, exact book exchange/receive age, average fill price, fill slippage, and the fraction of entry-side visible depth consumed;
- the same record also preserves decision-time spread/book age for later latency-drift analysis without confusing those values with fill-time liquidity;
- records are immutable, canonical, idempotent by opening-plan ID, conflict-detecting, and travel inside the normal continuous-paper state artifact;
- closed-trade attribution verifies market, side, opening timestamp, strategy decision, and feature lineage before using a record;
- live summaries compare overall, winners versus losers, and LONG versus SHORT while explicitly counting historical closes without exact fill-liquidity evidence and open/pending evidence records;
- the frozen review gate requires 30 matched prospective closed trades;
- the opening research observer is fail-open: capture failure is surfaced as research telemetry and cannot alter the already-computed paper opening result.

This diagnostic is descriptive only. It does not reject trades, change scanner ranking, alter sizing/risk, delay entries, change IOC behavior, or grant promotion/execution authority.

**LIVE TRADING: DISABLED.**


### Fixed 60-second delayed-entry same-exit contribution — 2026-09-27

The existing fixed +60s delayed-entry execution shadow now has a second derived diagnostic that translates full delayed fills into same-exit trade-contribution economics.

- it reuses the already-durable delayed-entry outcomes; no new delay, shadow state, or timing parameter is introduced;
- only full visible-book IOC delayed fills are evaluated;
- each delayed fill must match the actual closed trade by trade ID, opening-plan ID, market, side, and full quantity;
- the delayed entry price and delayed opening fee replace the actual opening price/fee;
- the observed actual exit price, actual exit fee, and actual funding cash PnL are held constant;
- the diagnostic reports actual versus estimated same-exit net PnL/R, estimated loss-to-win or win-to-loss flips, and side attribution;
- partial/no-fill/rejected/expired delayed outcomes are not assigned invented economics;
- missing journal trades or lineage mismatches remain explicit and block review readiness;
- the evidence gate is inherited from the fixed delayed-entry study: 30 closed shadow outcomes and 20 evaluated full delayed fills.

This is a **trade-contribution estimate**, not a portfolio counterfactual. A real 60-second delayed entry could change stop timing, funding exposure, later risk capacity, concurrent positions, missed entries, or replacement opportunities. The study therefore cannot authorize an execution change.

**LIVE TRADING: DISABLED.**


### Continuous-paper queued successor handoff — 2026-09-27

The continuous-paper workflow now minimizes worker restart gaps without allowing concurrent paper writers.

- the workflow uses one repository-level non-cancelling concurrency group, so push/schedule/manual successors queue behind the active continuous-paper run instead of racing it;
- the duplicate-run guard blocks only another genuinely `in_progress` worker; merely queued/pending successors no longer cause the starting run to skip;
- after the trader exits successfully and the durable state artifact is uploaded, the **same paper job** dispatches the exact successor run with the predecessor run ID and attempt;
- the old separate `continue` job is removed, eliminating an extra hosted-runner queue hop between durable-state upload and successor dispatch;
- the queued exact successor cannot begin until the active concurrency holder finishes, preserving the single-writer account-state boundary;
- watchdog/schedule/push runs remain available as recovery paths and still restore only trusted main-branch artifacts.

This changes workflow orchestration only. It does not alter market scanning, strategy decisions, position management, risk, fills, accounting, or execution authority.

**LIVE TRADING: DISABLED.**


### Prospective paired 60s vs 120s delayed-entry study — 2026-09-27

A second delayed-entry execution horizon is frozen prospectively to test whether waiting one additional minute improves or degrades the already-running 60-second entry shadow.

- the existing 60-second shadow remains unchanged and keeps its original durable evidence;
- a separate 120-second shadow uses the same visible-book IOC simulator, original paper quantity, original opening stop, risk ceiling, latency, slippage, and fee model;
- the 120-second shadow has its own durable state file and begins from its own first-deployment timestamp;
- only trades opened after the 120-second study begins are eligible for the paired comparison;
- paired economics are evaluated only when both 60-second and 120-second shadows obtained full visible-book IOC fills for the same paper trade;
- the paired same-exit estimate holds the actual observed exit price, exit fee, and funding constant and isolates only the incremental entry-price/entry-fee contribution of 120 seconds versus 60 seconds;
- non-full, missing, censored, or lineage-mismatched pairs are reported and never imputed;
- the review gate requires 30 prospective closed trades, 20 paired full fills, at least 5 LONG pairs, at least 5 SHORT pairs, zero missing shadow outcomes, and zero lineage mismatches.

This is an adaptive but prospectively frozen challenger created after the 60-second shadow showed early favorable entry-price evidence. Historical 60-second outcomes are not reused as paired 120-second evidence. Reaching the gate grants review readiness only and cannot alter the active paper entry timing.

**LIVE TRADING: DISABLED.**


### 60s delayed-entry fill-weighted contribution — 2026-09-27

The 60-second delayed-entry study now includes a second, stricter contribution view that does not discard partial or genuine no-fill outcomes.

- full delayed fills use the simulated delayed entry price and exact simulated entry fee;
- partial delayed fills keep only the quantity actually filled in the visible-book IOC;
- genuine no-fill outcomes contribute zero rather than inheriting the actual trade result;
- unresolved censored, missing-book, rejected, or expired observations are excluded rather than treated as missed trades;
- the observed exit price is held fixed for filled quantity;
- observed exit fees and funding are scaled linearly by the delayed fill fraction;
- unfilled quantity is not replaced by another trade;
- candidate R is expressed against the original paper trade's planned risk so the result measures account-level contribution loss/gain from reduced exposure.

This diagnostic exists specifically to test survivorship bias in the full-fill-only delay result. The original full-fill same-exit study remains unchanged and should be read beside this fill-weighted view.

The frozen review gate is 30 closed delayed-shadow outcomes and 20 evaluable full/partial/no-fill attempts with zero journal or lineage mismatches.

This is research-only and has no execution or promotion authority. It cannot delay entries, alter size, change stops, or submit orders.

**LIVE TRADING: DISABLED.**


### Fill-weighted paired 60s vs 120s delay — 2026-09-27

The paired 60-second versus 120-second delayed-entry study now has a second comparison that includes partial and genuine no-fill outcomes on both sides.

- each delay is valued with the same fill-weighted same-exit accounting used by the standalone 60-second contribution study;
- full and partial fills use the simulated visible-book IOC price/fee and only the quantity actually filled;
- genuine no-fills contribute zero;
- unresolved censored, missing-book, rejected, or expired outcomes make that pair non-evaluable rather than being imputed;
- both delays are compared on the same observed paper exit, with exit fees and funding scaled by each delay's fill fraction;
- the report explicitly measures when the 120-second challenger loses or gains fill fraction versus 60 seconds;
- source-pair counts expose which combinations of full/partial/no-fill drive the result.

The original paired full-fill-only study remains unchanged and isolates price/fee differences among trades that fully fill at both delays. This fill-weighted paired view instead asks whether a longer delay still helps after reduced exposure is charged.

The frozen review gate requires 30 prospective closed trades, 20 paired evaluable attempts, at least 5 LONG pairs, at least 5 SHORT pairs, zero missing shadow outcomes, and zero lineage mismatches.

This is research-only and has no execution or promotion authority. It cannot alter the active paper entry delay, quantity, stop, risk, or order flow.

**LIVE TRADING: DISABLED.**


### Delayed-entry fill-capacity diagnostic — 2026-09-27

The +60s delayed-entry shadow now preserves IOC attempt reason codes on completed outcomes and reports why delayed size is not fully filled.

- full, partial, and no-fill attempts are measured against the original paper position quantity;
- each partial fill reports its fill fraction;
- new partials are classified as visible-depth/slippage-boundary limited, risk-ceiling clipped, notional-ceiling clipped, or mixed risk/notional clipping;
- older partial outcomes that predate reason capture remain explicitly labeled `legacy_unknown_partial` and are never guessed;
- summaries are split by LONG/SHORT and by causal fill bucket;
- review readiness requires 30 evaluable delayed attempts and 10 cause-known partial fills with clean journal lineage.

This diagnostic cannot alter delay, order size, slippage, risk limits, scanner selection, or execution.

**LIVE TRADING: DISABLED.**


### Delayed-entry market-capacity split — 2026-09-27

The +60s delayed-entry fill-capacity diagnostic now separates market-side partial fills into two causal buckets using the exact delayed L2 snapshot and the frozen IOC slippage boundary:

- `visible_depth_exhausted`: all visible executable-side levels were consumed and no additional displayed size remained;
- `slippage_boundary_reached`: additional displayed size existed, but only beyond the allowed IOC slippage boundary.

Risk-ceiling and notional-ceiling clipping still take precedence when the IOC simulator reports those constraints. The additional capacity label is research-only metadata stored beside the delayed shadow outcome; it does not modify the authoritative IOC simulation, plan, fills, fees, risk envelope, or account state.

The capacity cause survives continuous-paper worker handoffs if the delayed attempt occurs before rotation and the actual paper trade closes afterward.

**LIVE TRADING: DISABLED.**


### Live delayed-entry attempt capacity preview — 2026-09-27

The +60s delayed-entry fill-capacity diagnostic now exposes completed delayed attempts for paper positions that are still open.

- the preview reads the same durable delayed-shadow state that will later become a closed outcome;
- each open attempted position reports market, side, IOC result, fill fraction, market-capacity cause, IOC reason codes, and observation lag;
- the preview survives worker handoffs because the underlying open delayed-shadow state is already durable;
- it exists only to reveal fill mechanics sooner; it does not create a second evidence record;
- formal fill-capacity readiness continues to count finalized closed outcomes only, so open attempts cannot be double-counted or accelerate the review gate.

This preview has no execution or promotion authority and cannot alter order timing, quantity, slippage, risk, account state, or live trading.

**LIVE TRADING: DISABLED.**


### Profit-lock execution shadow opening-lineage correction — 2026-09-27

The execution-aware profit-lock research stream now binds its opening risk envelope to the persisted opening plan, matching the authoritative journal contract.

- the actual paper position still supplies the filled quantity, VWAP entry price, side, and opening timestamp;
- the persisted opening plan supplies the original stop, cost buffer, and approved risk amount ceiling;
- this fixes a systematic research-only mismatch where `PaperPosition.planned_risk` represented actual fill risk while `TradeJournalEntry.initial_risk_amount` represented the approved opening risk ceiling;
- exact close-lineage checks remain strict; no mismatched historical close is repaired or admitted;
- the profit-lock execution-shadow state schema advances to v2, so the previously contaminated v1 mismatch counters are not carried into the corrected prospective sample;
- an incompatible v1 checkpoint starts a fresh research stream with an explicit restore warning, while the paper trader continues normally.

This changes only profit-lock research evidence. It does not change paper account risk, stops, fills, position management, strategy decisions, or execution authority.

**LIVE TRADING: DISABLED.**


### 60s delayed-entry contribution decomposition — 2026-09-27

The fill-weighted +60s delayed-entry study now decomposes each evaluated trade's candidate-minus-actual contribution into an exact accounting identity:

- **price effect**: delayed simulated entry-price improvement or deterioration on only the quantity that actually filled;
- **entry-fee effect**: delayed simulated entry fee versus the actual paper entry fee scaled to the same filled quantity;
- **exposure effect**: the observed paper trade contribution removed or retained because the delayed IOC filled less than the original quantity;
- **total delta**: price effect + entry-fee effect + exposure effect, which must reconcile exactly to the existing fill-weighted same-exit candidate delta.

The diagnostic reports the decomposition overall, by LONG/SHORT, by full/partial/no-fill source, and by the causal fill-capacity bucket when known.

This does not simulate replacement trades or change order quantity, delay, slippage, stops, risk ceilings, or execution. It is research-only accounting over the already-frozen delayed-entry shadow.

**LIVE TRADING: DISABLED.**


### 60s delayed-entry risk geometry — 2026-09-27

The +60s delayed-entry research now measures how the delayed fill price interacts with the original paper trade's risk budget.

- the persisted opening plan supplies the original stop and cost-buffer fraction;
- the closed paper journal supplies the actual entry quantity and original approved risk ceiling;
- the delayed shadow supplies the observed delayed average fill and filled quantity;
- risk utilization is delayed filled risk divided by the original paper risk ceiling;
- full-size risk ratio is the risk that the original quantity would consume at the delayed average fill divided by the original risk ceiling;
- risk-capacity fraction is the maximum fraction of original size that can fit that risk ceiling at the delayed average fill;
- unit-risk change compares delayed per-unit stop-and-cost risk with the actual entry's per-unit risk;
- the report separates risk-ceiling clips from full fills and splits results by side/cause.

A full-size risk ratio above 1 means the original size cannot fit the original risk budget at that delayed price/stop geometry. This diagnostic does not change the stop, risk ceiling, delayed quantity, delay, IOC simulator, or actual paper execution.

Review readiness requires 20 filled delayed attempts, including 5 risk-ceiling-clipped attempts, with clean journal/opening-plan lineage.

**LIVE TRADING: DISABLED.**


### Prospective 60s delayed price-confirmation study — 2026-09-27

A deployable delayed-entry hypothesis is frozen prospectively after the existing +60s research separated favorable full fills from harmful partial-price outcomes.

- candidate ID: `prospective-60s-price-confirm-v1`;
- wait exactly 60 seconds, using the already-frozen delayed visible-book IOC evidence;
- compare the simulated delayed average fill with the immutable original opening-plan execution reference;
- for LONG, confirm only when the delayed average fill is no higher than the original reference;
- for SHORT, confirm only when the delayed average fill is no lower than the original reference;
- a confirmed full or partial delayed attempt keeps the existing fill-weighted same-exit contribution estimate;
- a worse-price delayed attempt or genuine no-fill is shadow-skipped and contributes zero;
- unresolved/censored delayed outcomes are not imputed;
- only paper trades opened after this study's durable `started_at_ms` count. Existing touched delayed-entry outcomes cannot validate the candidate;
- exact trade/outcome/opening-plan lineage is required.

The candidate reports **closed-trade contribution only**, not portfolio PnL. A skipped trade could change later risk capacity, cooldowns, concurrent positions, replacement opportunities, and exit timing.

The frozen review gate requires:

- 30 prospectively evaluated closed trades;
- 10 price-confirmed delayed trades;
- 10 skipped trades;
- zero missing opening plans, lineage mismatches, unresolved outcomes, or missing delayed outcomes.

Meeting the gate means `ready_for_review` only. It grants no promotion or execution authority and cannot delay or skip an actual paper trade.

**LIVE TRADING: DISABLED.**

### Prospective adaptive 60s/120s delayed-entry selector — 2026-09-27

A new adaptive delay candidate is frozen prospectively after the first fixed 60s-versus-120s results were already observed. Earlier paired outcomes are therefore excluded from this study.

Frozen rule:

- at the 60-second decision point, use the fresh 1-minute allMids markout only if it was observed no later than the 60-second IOC observation;
- if signed 1-minute gross R is below zero, keep waiting and use the existing 120-second delayed-entry shadow;
- otherwise use the existing 60-second delayed-entry shadow;
- no threshold sweep or optimizer is permitted inside this candidate.

The candidate reuses the existing visible-book IOC outcomes and fill-weighted same-exit accounting. Full fills, partial fills, and genuine no-fills are evaluable; unresolved delayed observations remain excluded. Unfilled quantity contributes zero and is not replaced. Observed exits are held constant, so this remains a trade-contribution study rather than a portfolio counterfactual.

The durable candidate start timestamp survives worker handoffs. Review readiness requires:

- 30 prospective closed trades;
- 20 causally evaluable trades;
- at least 5 trades selecting 60 seconds;
- at least 5 trades selecting 120 seconds;
- no causality or lineage violations.

The study is research-only and grants no execution or promotion authority. It cannot delay or place the actual paper order.

**LIVE TRADING: DISABLED.**


### Adaptive delayed-entry concentration robustness — 2026-09-27

The causal 60s/120s adaptive delayed-entry selector now reports descriptive concentration stress tests without changing its frozen prospective rule or readiness gate.

- adaptive edge versus always-60s and always-120s is decomposed by market;
- the study reports the largest absolute single-trade and single-market contribution to each incremental edge;
- leave-one-trade-out minimum delta shows the worst remaining edge after removing any one evaluated trade;
- leave-one-market-out minimum delta shows the worst remaining edge after removing any one market;
- explicit booleans report whether a positive edge survives every single-trade removal and every single-market removal;
- robustness output is descriptive only and cannot turn a collecting study into review-ready.

This prevents a future small-sample adaptive advantage from looking broad when it is actually concentrated in one lucky trade or one token.

**LIVE TRADING: DISABLED.**


### Adaptive delayed-entry temporal robustness — 2026-09-27

The adaptive 60s/120s selector now also reports chronological stability without changing its frozen rule or readiness gate.

- causal evaluable trades are ordered by actual close time;
- the sequence is split into four chronological blocks;
- a full block requires five causal trades, matching the selector's 20-trade causal review gate;
- each block reports adaptive delta versus always-60s and always-120s;
- the diagnostic reports how many full blocks remain positive versus each fixed delay and whether all four full blocks are positive;
- incomplete blocks remain visible but do not count as full stability blocks.

This is descriptive robustness only. It cannot make the selector review-ready, cannot alter paper entry timing, and has no promotion or execution authority.

**LIVE TRADING: DISABLED.**


### Prospective fill-aware 60s/120s delayed-entry selector — 2026-09-27

A second adaptive delayed-entry hypothesis is frozen prospectively after the existing 60-second fill-quality results were already observed. Earlier outcomes are excluded from this candidate.

Frozen causal rule:

- if the 60-second visible-book IOC shadow fully fills the original quantity, select the 60-second delayed-entry contribution;
- if the 60-second shadow partial-fills or genuinely no-fills, keep waiting and select the existing 120-second delayed-entry contribution;
- if either required delayed-entry stream is missing or non-evaluable, the trade is not counted as causally evaluable;
- no fill-fraction threshold sweep, optimizer, market exception, or side exception is permitted inside this candidate.

Economic accounting reuses the existing fill-weighted same-exit research contract. Filled quantity keeps the observed trade exit, scaled exit fee, and scaled funding; unfilled quantity contributes zero and is not replaced. This is therefore a trade-contribution study, not a portfolio counterfactual.

The candidate has its own durable start timestamp so the partial-fill pattern that motivated it cannot enter prospective validation. Review readiness requires:

- 30 prospective closed trades;
- 20 causally evaluable trades;
- at least 5 selections of 60 seconds;
- at least 5 selections of 120 seconds;
- no missing required 60s/120s outcomes, non-evaluable delayed outcomes, or lineage mismatches.

Meeting the gate means only `ready_for_review`. The selector has no execution or promotion authority and cannot delay or place the actual paper order.

**LIVE TRADING: DISABLED.**


### Prospective markout-vs-fill-aware delay selector comparison — 2026-09-28

A paired prospective comparison now measures the two existing adaptive delayed-entry selectors on the same future paper trades without introducing a third selector.

Compared rules:

- **markout selector**: at the 60-second decision point, wait to 120 seconds only when a fresh causally available 1-minute allMids gross-R markout is negative;
- **fill-aware selector**: use 60 seconds only when the 60-second visible-book IOC shadow fully fills the original quantity; otherwise wait to 120 seconds.

The comparison has its own durable start timestamp created after both selector definitions already existed, so earlier touched evidence cannot validate either side.

Only trades with causally evaluable 60-second and 120-second delayed-entry outcomes plus the required 1-minute mid-markout record enter the paired comparison. Both selectors reuse the same fill-weighted same-exit accounting contract. No replacement trades, changed exits, capacity effects, or portfolio PnL are inferred.

The primary evidence is **disagreement trades**. Agreements are counted for coverage but cannot create selector edge. For each disagreement, the study reports which selector's chosen delay produced the higher fill-weighted same-exit trade contribution.

Review readiness requires:

- 30 prospective closed trades;
- 20 causally evaluable paired trades;
- 10 same-trade selector disagreements;
- zero missing required mid/60s/120s outcomes, non-evaluable delayed outcomes, or lineage mismatches.

Meeting the gate means only `ready_for_review`. The comparison has no execution or promotion authority and cannot alter actual paper entry timing.

**LIVE TRADING: DISABLED.**


### Fixed-schedule delayed-entry portfolio shadow — 2026-09-28

The 60-second delayed-entry research now includes a portfolio-level accounting shadow over the same observed closed-trade schedule.

- actual paper openings are compared with the existing +60s visible-book delayed fill outcomes;
- full fills, partial fills, and genuine no-fills retain the existing fill-weighted economics;
- candidate exposure begins at the observed delayed fill timestamp and ends at the actual observed trade close;
- the study measures concurrent positions, overlapping openings, peak gross notional, peak planned risk, position/notional/risk exposure-hours, cumulative realized contribution, and realized-contribution drawdown;
- every candidate fill is checked against the immutable opening plan and original stop/risk geometry;
- unresolved delayed observations are excluded rather than treated as no-fills;
- review readiness requires 30 closed shadow outcomes, 20 evaluable delayed attempts, at least 5 actual overlap openings, zero unresolved delayed outcomes, and zero journal/plan/lineage/risk-ceiling integrity failures.

This closes the concurrency/exposure blind spot in per-trade delayed-entry contribution studies, but it remains a **fixed observed schedule** study. It does not invent replacement trades, change exit timestamps, replay strategy decisions under altered capacity, or model unrealized mark-to-market equity. Those limitations are surfaced live and prevent this study from claiming a full alternate portfolio backtest.

**LIVE TRADING: DISABLED.**


### Fixed-schedule delayed-entry mark-to-market portfolio shadow — 2026-09-28

The existing 60-second delayed-entry fixed-schedule portfolio study now has a stricter observed-mark equity companion.

- the same evaluable delayed-entry outcomes are matched to complete exact trade paths;
- actual positions begin at the observed paper entry, while candidate positions begin at the observed delayed fill timestamp and use the delayed filled quantity/price;
- entry fees are applied at open; exit fees and total observed funding settle at the actual close;
- while positions are open, contribution equity uses each position's latest observed exact-path mark carried forward until its next mark;
- the study reports maximum observed contribution-equity drawdown, minimum/maximum observed contribution equity, concurrent positions, overlap openings, and maximum carried-mark age;
- no-fill delayed outcomes create no candidate position;
- incomplete or missing exact paths, unresolved delayed outcomes, and lineage mismatches remain explicit and block review readiness;
- review readiness requires 30 closed shadow outcomes, 20 complete-path evaluated trades, at least 5 actual overlap openings, and zero integrity gaps.

This closes the unrealized-equity blind spot in the fixed-schedule delayed-entry portfolio study, but it still does not replay strategy decisions under altered capacity, invent replacement trades, or change exit timing. Intratrade funding timing is also not reconstructed; observed total funding settles at the actual close.

**LIVE TRADING: DISABLED.**


### Fixed-schedule delayed-entry portfolio capacity overlay — 2026-09-28

The 60-second delayed-entry research now checks the alternate fixed schedule against the same aggregate risk policy boundaries used by the paper trader.

- delayed candidate positions use their observed delayed fill price/quantity and immutable original stop/cost geometry to reconstruct planned risk;
- non-cohort trades that overlap the delayed cohort stay on their observed schedule as background positions;
- exact trade paths mark open positions to observed contribution equity at every candidate opening;
- every opening is checked against max aggregate open risk, the shared runtime correlation-bucket risk ceiling, and max gross leverage using candidate equity at that moment;
- available-margin capacity, visible-liquidity capacity, and liquidation-buffer checks are not reconstructed in this overlay and remain explicit limitations;
- both delayed candidate openings and unchanged background openings are checked, because a delayed position can change whether a later observed opening still fits;
- actual-schedule capacity violations are treated as reconstruction/integrity failures; candidate-schedule violations are the research result and are surfaced rather than silently resized;
- no-fill delayed outcomes create no candidate exposure;
- missing plans/paths, incomplete paths, unresolved delayed outcomes, and lineage mismatches remain explicit.

Review readiness requires 30 closed delayed-shadow outcomes, 20 filled delayed candidate positions, at least 5 candidate overlap openings, zero unresolved/missing/incomplete/lineage gaps, and zero capacity violations in the reconstructed actual baseline.

The fixed overlay remains intact, and a causal admission shadow now applies those same three capacity ceilings chronologically. If an opening would breach a configured ceiling, that hypothetical opening is skipped completely; its entry fee, later marks, and close contribution are removed, and subsequent opening opportunities are evaluated against the surviving portfolio. The observed baseline must reconstruct with zero rejected openings before the evidence can become review-ready.

This still is not a full alternate strategy replay. The admission shadow does not resize rejected orders, rerun strategy generation, invent replacement trades, change exit timing, reconstruct available-margin or liquidation-buffer policy, or infer unseen liquidity. Candidate admission rejections are valid research outcomes; actual-baseline admission rejections are integrity failures.

**LIVE TRADING: DISABLED.**


### allMids markout opening-risk lineage repair — 2026-09-28

The prospective allMids entry-markout shadow now receives the immutable approved opening risk ceiling from the persisted opening plan before it tracks or reconciles a paper position.

- authoritative paper positions are not mutated;
- the shadow no longer compares actual filled position risk against the journal's approved opening risk ceiling;
- close lineage remains strict for market, side, entry price, opening timestamp, quantity, and approved risk;
- the allMids research-state schema is bumped so previously accumulated systematic lineage-mismatch counters are discarded rather than carried into future readiness;
- an incompatible old state fails open for trading and restarts only this research stream from the fixed protocol.

This repair changes research evidence integrity only. It does not alter entries, stops, sizing, risk, fills, accounting, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry capacity baseline filled-risk repair — 2026-09-28

The fixed-schedule delayed-entry capacity overlay now reconstructs observed paper risk from the actual filled position rather than the larger approved opening-risk ceiling.

- every relevant observed position must resolve its persisted opening plan;
- observed planned risk is recomputed with the same contract as paper accounting: actual fill notional times the actual entry-to-stop loss fraction plus the immutable plan cost buffer;
- the reconstructed observed risk must remain at or below the approved opening-risk ceiling;
- background positions and delayed-cohort positions use the same filled-risk reconstruction;
- missing opening plans and plan/trade lineage mismatches remain explicit integrity gaps;
- the runtime's single configured `crypto_beta` correlation bucket assumption remains unchanged and matches the current opening engine;
- the actual admission baseline must reconstruct with zero rejected observed openings before the delayed-capacity study can become review-ready.

This fixes research-only false capacity rejections caused by treating partially filled positions as if they consumed their full approved risk envelope. It does not change the paper risk engine, paper positions, sizing, entries, exits, or live-order capability.

**LIVE TRADING: DISABLED.**


### Trade-path venue-leverage lineage capture — 2026-09-28

Exact venue leverage is now retained with new continuous-paper trade-path evidence so the delayed-entry portfolio research can later reconstruct available-margin capacity without guessing market leverage.

- each opening trace now carries the exact `InstrumentExecutionSpec` used by the risk/execution path;
- filled openings immediately stage their venue max leverage into the durable open trade-path header;
- active lifecycle checkpoints also carry venue max leverage, so a worker restart can recover or upgrade an older open-path header before that position closes;
- the trade-path record schema is versioned to v2 for leverage-aware paths while existing closed v1 records remain valid and readable;
- legacy open-path headers can be upgraded in place when authoritative position leverage becomes available;
- leverage drift for the same opening-plan identity is treated as an evidence-lineage conflict instead of silently accepted.

This is an evidence prerequisite, not a trading-rule change. The delayed-entry capacity overlay still reports available-margin capacity as unmodeled until a separate causal replay consumes this new leverage lineage. Entries, sizing, stops, fills, risk limits, and live-order capability are unchanged.

**LIVE TRADING: DISABLED.**


### Delayed-entry available-margin capacity replay — 2026-09-28

The fixed-schedule delayed-entry portfolio capacity study now consumes the exact venue-max-leverage lineage introduced by #573 and reconstructs the paper engine's available-margin capacity causally.

- leverage-aware trade-path v2 evidence supplies each position's exact venue max leverage;
- legacy v1 trade paths remain readable, but a relevant v1 path is counted as missing venue-leverage evidence and blocks review readiness rather than inheriting a guessed leverage;
- active reserved margin is reconstructed from the latest causally available mark notional divided by `min(paper_max_gross_leverage, venue_max_leverage)`, matching paper accounting;
- available margin is reconstructed as `max(0, equity - reserved_margin)`;
- a new opening's margin capacity uses `available_margin * max_available_margin_fraction * min(risk_max_gross_leverage, opening_venue_max_leverage)`, matching the independent risk engine;
- the fixed overlay reports margin-capacity violations/headroom/utilization, while the causal admission shadow rejects a hypothetical opening that exceeds the same available-margin capacity and reevaluates later openings against the surviving portfolio;
- the observed paper baseline must still reconstruct with zero capacity violations and zero admission rejections before the study can become review-ready;
- visible-liquidity capacity and liquidation-buffer policy remain explicitly unmodeled, and rejected hypothetical orders are not resized or replaced.

This is research/shadow accounting only. It does not change strategy thresholds, risk limits, paper sizing, actual entries/exits, execution cadence, position management, or any live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry liquidation-buffer replay — 2026-09-28

The delayed-entry portfolio capacity study now replays the same paper liquidation-distance gate used by the independent risk engine.

- each observed and delayed candidate opening uses its exact persisted stop, entry price, venue max leverage, and the frozen paper max leverage;
- the paper liquidation surrogate is recomputed at that opening price with `min(paper_max_gross_leverage, venue_max_leverage)`;
- LONG and SHORT stop geometry follows the existing risk-engine contract, including the requirement that the surrogate liquidation level remain beyond the stop;
- the reconstructed liquidation-distance / stop-distance multiple must meet `min_liquidation_stop_multiple`;
- the fixed overlay reports liquidation-buffer violations and minimum multiple/headroom;
- the causal admission shadow rejects a hypothetical opening that fails the same gate and evaluates later openings against the surviving portfolio;
- the observed paper baseline must reconstruct with zero such violations/rejections before review readiness can pass;
- visible-liquidity capacity remains the remaining explicitly unmodeled market-cap gate.

This is research/shadow accounting only. It does not change the real paper risk engine, strategy thresholds, sizing, stops, fills, execution cadence, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry visible-liquidity replay — 2026-09-28

The delayed-entry portfolio capacity study now carries exact 25bps depth evidence into the same visible-liquidity cap used by the independent paper risk engine.

- the delayed-entry execution shadow state is versioned from v2 to v3 and records the exact delayed execution reference price plus entry-side and exit-side 25bps notional from the delayed L2 book using the existing microstructure feature calculator;
- v2 durable shadow state remains restorable, but legacy delayed outcomes keep depth as unknown rather than receiving fabricated values;
- observed paper openings use their existing authenticated opening-fill-liquidity evidence and must match plan, strategy, feature, market, direction, and opening timestamp lineage;
- both observed and delayed openings compute capacity as `min(entry_side_depth_25bps, exit_side_depth_25bps) * max_visible_depth_fraction`, and compare that capacity to the pre-IOC planned notional at the opening reference price rather than the eventual fill notional;
- the fixed overlay reports visible-liquidity violations, utilization, and notional headroom;
- the causal admission shadow rejects a hypothetical opening when its filled notional exceeds the same visible-depth capacity and then evaluates later openings against the surviving portfolio;
- missing original-opening or delayed depth evidence is an explicit readiness gap; it never falls back to IOC fill size or a synthetic depth assumption;
- venue-minimum-notional replay remains outside this overlay and is the next market-cap contract to reconcile explicitly.

This remains research-only accounting. It does not alter paper entry selection, risk approval, sizing, fills, stops, execution cadence, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry venue minimum-notional replay — 2026-09-28

The delayed-entry portfolio capacity study now replays the paper planner's native-perp minimum-notional gate on the same pre-IOC opening notional already carried for visible-liquidity checks.

- the current mainnet paper instrument minimum is the frozen `native_perp_min_notional`, so the shadow receives that exact execution-config value instead of hard-coding a separate threshold;
- observed openings use `plan.requested_quantity * plan.execution_reference_price`;
- delayed candidates use the original filled position quantity times the exact delayed execution reference price captured by the v3 delayed-entry shadow;
- the venue minimum is checked on that pre-IOC planned notional, not on eventual fill notional, so a valid order that partially fills below the minimum is not falsely rejected;
- the fixed overlay reports minimum-notional violations and minimum notional headroom;
- the causal admission shadow rejects a hypothetical fixed-size opening below the venue minimum and then evaluates later openings against the surviving portfolio;
- this remains a reject-only shadow: it does not invent counterfactual resizing, replacement trades, altered fills, or changed exits. Risk-ceiling clipping observed by the delayed IOC shadow remains separately measurable rather than being converted into synthetic resized fills here.

This is research-only accounting. It does not change paper strategy selection, risk limits, order sizing, fills, stops, execution cadence, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry MTM funding-timing replay — 2026-09-28

The 60-second delayed-entry mark-to-market portfolio shadow now applies funding at the exact recorded funding boundaries instead of settling a proportional funding estimate at the actual close.

- each journal trade's `funding_event_ids` must resolve to immutable paper execution funding accruals for the same market and lifecycle;
- stored funding cash deltas are revalidated from signed quantity, recorded oracle price, and recorded funding rate before use;
- actual portfolio equity receives each verified accrual at its recorded hourly boundary;
- a delayed candidate receives only boundaries strictly after its delayed open and through the unchanged actual close;
- candidate funding quantity is the recorded boundary quantity scaled by the delayed IOC fill fraction, preserving proportional actual reduction state without inventing a new reduction path;
- funding that occurred before the delayed candidate existed is no longer smeared into its close PnL;
- missing funding accrual lineage is an explicit readiness gap; inconsistent accrual economics remain a lineage mismatch;
- entry fees remain timed at open and exit fees remain settled at the unchanged actual close; replacement trades and changed exit timing are still not modeled.

This is research-only accounting. It does not alter paper funding reconciliation, strategy selection, fills, sizing, exits, execution cadence, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry capacity funding-timing replay — 2026-09-28

The delayed-entry portfolio capacity and causal admission shadows now apply funding at the exact recorded funding boundaries before evaluating later opening opportunities.

- funding lineage uses the same validated journal-to-execution accrual contract as the delayed-entry MTM portfolio;
- actual positions receive each verified funding cash delta at its recorded boundary;
- delayed candidates receive only funding boundaries strictly after their delayed open, with the recorded boundary quantity scaled by the delayed IOC fill fraction;
- close contribution excludes funding once those boundary events are replayed, preventing double counting;
- fixed-schedule capacity checks therefore see funding-adjusted equity and margin before later openings;
- the causal admission shadow applies funding only for admitted positions; funding events belonging to rejected hypothetical openings are skipped and cannot leak into later equity;
- missing funding accrual lineage is an explicit readiness gap rather than falling back to proportional close funding;
- the shadow still does not invent replacement trades or changed exits.

This remains research-only accounting. It does not alter paper funding reconciliation, strategy selection, risk limits, sizing, fills, exits, cadence, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry original-stop survivability — 2026-09-28

The 60-second delayed-entry research now measures whether a filled delayed candidate definitely crosses the immutable original stop before the actual trade close.

- only closed delayed outcomes with an actual delayed fill are evaluated; no-fill outcomes contribute no exposure;
- the original stop comes from the immutable closed-trade journal lineage;
- only complete, gap-free exact trade paths are eligible;
- marks at the exact delayed-open millisecond are excluded because their causal order relative to the hypothetical fill is not preserved by this study;
- for LONG candidates, the first later observed mark at or below the original stop is a definite crossing; for SHORT candidates, the first later observed mark at or above the original stop is a definite crossing;
- the study reports definite crossings, observed survivors, crossing fraction, and time-to-stop statistics;
- a survivor means the complete observed path did not cross the original stop after the delayed fill existed; it is not a claim about unobserved intramillisecond prices;
- the study does not invent stop fill prices, slippage, replacement trades, or the complete counterfactual exit-management policy.

This is a research-only survivability diagnostic. It does not change paper stops, exits, risk limits, sizing, execution cadence, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry fill-weighted funding correction — 2026-09-28

The 60-second delayed-entry fill-weighted contribution study now has a separate funding-corrected overlay.

- the existing legacy fill-weighted metric remains unchanged for historical comparability;
- filled delayed candidates resolve exact recorded funding accrual lineage from the execution store;
- candidate funding includes only verified funding boundaries strictly after the delayed fill causally exists;
- each recorded boundary quantity is scaled by the delayed fill fraction, preserving observed later position reductions instead of assuming the opening quantity survives unchanged;
- genuine no-fill outcomes contribute zero and require no funding lineage because no hypothetical position exists;
- missing funding accruals or inconsistent funding lineage block corrected review readiness rather than falling back to whole-trade funding;
- telemetry shows legacy scaled funding, exact post-delay funding, the funding-only PnL correction, and corrected candidate contribution beside the legacy estimate.

The corrected overlay still assumes the actual recorded exit price and scales the actual exit fee by delayed fill fraction. It does not model changed exits, replacement trades, or stop fills.

This is research-only accounting. It does not change strategy, risk, sizing, paper execution, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry contribution funding decomposition — 2026-09-28

The 60-second delayed-entry contribution decomposition now has a funding-aware companion that makes funding timing an explicit fourth accounting effect.

- the legacy three-effect identity remains unchanged for comparability: price effect + entry-fee effect + exposure effect = legacy total delta;
- the corrected identity is: price effect + entry-fee effect + exposure effect + funding timing effect = corrected total delta;
- funding timing effect is exactly the difference between the legacy whole-trade scaled funding assumption and exact verified funding boundaries strictly after the delayed fill exists;
- the corrected decomposition reuses the same immutable funding accrual lineage and quantity-scaling logic as the funding-corrected fill-weighted overlay;
- genuine no-fill outcomes keep a zero funding-timing effect because no delayed position exists;
- missing or inconsistent funding lineage blocks corrected review readiness rather than being folded into exposure or silently estimated;
- live telemetry shows legacy versus corrected total delta and the explicit funding timing bridge without replacing the existing legacy decomposition table.

This remains a same-recorded-exit contribution study. It does not simulate stop fills, changed exits, replacement trades, or strategy changes.

**LIVE TRADING: DISABLED.**


### Delayed-entry same-exit stop-validity partition — 2026-09-28

The funding-corrected 60-second delayed-entry same-exit contribution is now partitioned by original-stop survivability.

- filled delayed candidates reuse the exact complete, gap-free trade-path stop classifier;
- candidate economics reuse the exact funding-corrected same-exit calculation;
- candidates whose observed path definitely crosses the immutable original stop before the recorded close are classified separately from candidates that survive the observed path to that close;
- telemetry reports total same-exit candidate PnL, PnL sitting on definite stop-crossed paths, PnL on observed survivors, and the same split for delta versus actual;
- the absolute share of candidate PnL sitting on definite stop crossings is reported as a contamination diagnostic;
- genuine no-fills require neither path nor funding evidence because no delayed position exists;
- incomplete/gapped paths, missing funding lineage, invalid candidate timing, and lineage mismatches block review readiness.

A stop-crossed candidate's recorded-close PnL is flagged as path-invalid evidence. It is not converted into a synthetic stop-fill PnL, because executable stop price/slippage is not modeled yet.

This remains research-only and changes no stops, exits, sizing, risk, cadence, paper execution, or live-order capability.

**LIVE TRADING: DISABLED.**


### Delayed-entry stop-exit proxy range — 2026-09-28

The 60-second delayed-entry stop analysis now estimates how definite original-stop crossings change candidate economics without pretending the missing exit-side L2 book is known.

For every filled delayed candidate with a complete, gap-free exact mark path:

- the existing funding-corrected same-recorded-exit contribution remains the comparison baseline;
- candidates that never cross the immutable original stop keep that same-exit contribution in every proxy cohort;
- definite stop-crossed candidates are repriced under three full-quantity exit proxies:
  - idealized exit at the immutable original stop;
  - exit at the first observed stop-crossing mark;
  - exit at the first crossing mark pushed to the configured paper IOC slippage boundary;
- each proxy charges the running paper configuration's taker-fee rate;
- funding is settled only for verified boundaries strictly after the delayed open and strictly before the stop trigger;
- if a funding boundary occurs at the exact stop-trigger millisecond, that trade is excluded as timing-ambiguous rather than assigned an arbitrary event order;
- telemetry reports whole-cohort PnL and delta versus actual under all three proxies, how much same-exit edge disappears at the IOC boundary proxy, and how many positive same-exit stop-crossed candidates become nonpositive.

These are price-and-cost proxies, not executable stop simulations. Exit-side L2 depth is not reconstructed, so partial stop fills, no-fill remainder behavior, and the exact average stop fill price are still unmodeled.

This is research-only evidence. It changes no live paper stops, exits, sizing, risk limits, cadence, or order authority.

**LIVE TRADING: DISABLED.**



### Delayed-entry reference-vs-fill risk geometry — 2026-09-28

The 60-second delayed-entry risk diagnostic now separates risk that already exists at the exact delayed execution reference price from risk introduced later by the visible-book IOC fill path.

- every evaluable delayed attempt, including a genuine no-fill, measures the immutable full-size risk geometry at the delayed execution reference price;
- filled attempts keep the existing average-fill risk utilization and capacity metrics;
- telemetry now distinguishes pre-IOC resize pressure from fill-path risk clipping;
- a trade can therefore show that the delayed reference still fit the original risk ceiling while adverse execution pushed the requested full size beyond that ceiling;
- missing delayed reference-price lineage is explicit and blocks review readiness rather than being reconstructed from the eventual fill;
- side and capacity-cause partitions are preserved for both reference-price and average-fill views.

This is research-only attribution. It does not resize orders, change stops, loosen risk ceilings, alter paper execution, or enable live orders.

**LIVE TRADING: DISABLED.**



### Original-stop executable-book capture — 2026-09-28

The continuous paper trader now preserves the exact L2 evidence needed to replay an original-stop reduce-only IOC without bypassing the paper engine's latency contract.

- the observer reads the original stop from the persisted opening plan, not the mutable current position stop;
- before a stop plan exists, the durable candidate crossing follows the latest authoritative mark exactly: a later still-crossed mark replaces it, while a recovery back inside the original stop cancels the unstaged crossing;
- the first subsequent mainnet L2 snapshot creates stop-plan evidence only when the latest mark still satisfies the original stop, matching the paper manager's actual decision point;
- once that book stages the stop-exit plan reference price and exact plan-time instrument metadata, later mark recovery no longer cancels it, matching the paper adapter's pending reduce-only behavior;
- if the plan-creation book arrives before paper IOC latency has elapsed, the pending plan remains durable across worker restarts and capture continues until the first latency-eligible L2 book;
- the execution book preserves full bid/ask levels, source/schema provenance, timestamps, and its own instrument metadata so later replay can detect instrument-version drift exactly as paper execution would;
- when the first post-crossing book is already latency-eligible, the same snapshot serves as both plan and execution evidence;
- the capture runs before paper position management but has no execution authority and fails open if its own research state breaks;
- non-crossed positions create no stop-book record, avoiding continuous full-book storage.
- the store persists a one-time capture-start timestamp; restarts preserve the original boundary so later exact-stop replay can exclude pre-capture legacy trades instead of treating them as missing evidence;

This closes the evidence-collection prerequisite behind the delayed stop-exit proxy. Existing historical trades without this prospective capture remain explicitly unmodeled; no L2 history is synthesized from marks or candles.

**LIVE TRADING: DISABLED.**



### Delayed-entry exact stop-L2 heartbeat — 2026-09-28

The continuous paper heartbeat now exposes the manager-triggered 60-second delayed-entry stop replay against prospectively captured L2 evidence.

- the exact replay sits beside the older stop price-proxy range rather than replacing it;
- it reuses the live paper engine's reduce-only planning and visible-book IOC semantics;
- transient mark crossings that never create a paper-manager stop plan remain same-exit survivors when capture integrity is clean;
- full stop exits receive exact visible-depth fill economics, including entry fee, stop fee, and funding available by execution time;
- partial fills, no-fills, quantized position remainders, planning/execution rejections, and pending evidence remain explicitly unresolved;
- trades opened before the durable stop-book capture boundary are excluded as legacy evidence instead of counted as missing;
- the capture observer's own error is passed into the replay, so degraded stop-book collection blocks clean readiness;
- the wrapper is fail-open for the runtime: a replay calculation failure disables only this research payload and cannot stop the paper trader heartbeat.

This is research-only observability. It changes no strategy decisions, stops, sizing, risk limits, paper execution, cadence, or live-order authority.

**LIVE TRADING: DISABLED.**



### Prospective top-10 + no LONG-trend intersection — 2026-09-28

A new frozen prospective entry-screen candidate now tests whether the two strongest current loss-filtering signals reinforce each other when combined.

The rule is fixed as:

- require the persisted opening scanner rank to be `1-10`, using rank evidence no older than 300 seconds;
- reject `LONG` entries whose persisted decision fact names `trend` as the lead strategy;
- admit only when both conditions pass.

This candidate starts from a new durable `started_at_ms` on the first worker that runs the merged code. Earlier evidence from the standalone LONG+trend and top-10 studies motivated the candidate but does **not** count toward its review gate. That keeps the intersection test prospective rather than converting an observed combination into retrospective evidence.

The study records exact decision-fact and opening-rank lineage, separates blocked contribution into `long_trend`, `rank_above_10`, and `long_trend_and_rank_above_10`, and requires zero missing/stale attribution before review readiness. Its frozen gate remains 30 prospective closed trades, at least 10 blocked trades, and at least 10 allowed trades.

This is closed-trade contribution evidence only. Skipped trades contribute zero; replacement trades, changed portfolio capacity, and changed exits are not modeled. The candidate has no promotion or execution authority and does not alter paper entries.

**LIVE TRADING: DISABLED.**



### Prospective entry-filter robustness diagnostics — 2026-09-28

The prospective LONG+trend, top-10 rank, and fresh combined top-10 + no LONG-trend studies now carry descriptive robustness diagnostics alongside their frozen readiness gates.

For each attributed cohort the diagnostics report:

- total trade-contribution delta from blocked trades;
- largest absolute single-trade contribution and its share of absolute blocked contribution;
- the minimum remaining delta after removing any one blocked trade;
- largest absolute market contribution and the minimum remaining delta after removing any one contributing market;
- four chronological blocks, including how many full blocks have positive filter delta.

This is a concentration/stability check, not a new promotion rule. It does not alter the candidate definition, prospective start boundary, evidence gate, paper admission, sizing, stops, risk, cadence, or execution. A candidate may be review-ready while still showing weak robustness, and the dashboard now keeps those statements separate.

**LIVE TRADING: DISABLED.**



### Stop-L2 prospective cohort integrity — 2026-09-28

The exact delayed-entry stop-L2 replay now defines its integrity cohort at the correct stage boundary.

- the durable stop-book capture start is applied before delayed-entry source classification, so every pre-capture outcome is excluded as legacy regardless of whether the delayed entry later filled, expired, was rejected, or lacked a usable delayed book;
- post-capture delayed-entry outcomes that never created an evaluable delayed position remain counted by source, but they no longer poison stop-exit integrity because there is no counterfactual position to stop;
- the backward-compatible `unresolved_outcomes` fields remain present for existing consumers, while new `non_evaluable_entry_outcomes` and `non_evaluable_source_counts` fields state the semantics directly;
- actual stop-replay integrity still fails closed on missing journal/path/funding lineage, path gaps, invalid timing, stop-book capture errors, pending stop evidence, or a degraded capture observer;
- Issue #469 now renders the full delayed-entry source mix, post-capture non-evaluable source counts, and every upstream stop-L2 integrity counter.

This changes research cohort accounting only. It does not make rejected or expired entries profitable, does not synthesize a position, does not change delayed-entry readiness elsewhere, and has no execution or promotion authority.

**LIVE TRADING: DISABLED.**



### Exact Decimal aggregation for delayed contribution decomposition — 2026-09-28

The delayed-entry contribution decomposition now aggregates accounting components with exact base-10 coefficient alignment instead of relying on separate finite-precision Decimal summation paths.

This fixes a live research-only failure where every per-trade decomposition reconciled exactly, but the aggregate price + entry-fee + exposure sums could differ from the separately accumulated total delta by a tiny rounding residue such as `1E-26`. The same exact aggregation is applied to the funding-corrected decomposition so its multi-part accounting identity cannot fail for the same reason.

The change affects research aggregation only. Per-trade economics, fills, fees, funding, risk, paper execution, and all promotion gates are unchanged.

**LIVE TRADING: DISABLED.**



### Fixed-schedule portfolio timelines for prospective entry filters — 2026-09-28

The three prospective entry-filter studies now publish a fixed observed-schedule portfolio timeline beside their trade-contribution and residual-loss diagnostics.

For each attributed closed trade, the candidate timeline removes trades rejected by the frozen filter while reusing the actual filled size, opening time, close time, and realized economics for trades that remain admitted. The dashboard reports actual vs candidate realized contribution, maximum realized drawdown, concurrent positions and overlap openings, maximum gross notional, maximum planned risk, and the blocked cohort's actual PnL.

This is deliberately narrower than a causal portfolio backtest. It does not invent replacement opportunities, resize later trades from changed equity, change exit timing, or reconstruct unrealized-equity paths. It is descriptive only and does not change any prospective readiness gate.

**LIVE TRADING: DISABLED.**



### Delayed-stop causal path-gap window — 2026-09-28

The delayed-entry original-stop survivability, same-exit stop-validity, stop-exit proxy, and exact stop-L2 replay now judge mark-path gaps only over the interval in which the delayed candidate position actually exists: strictly after the delayed open through the actual close.

Continuous paper trade paths carry the session's durable gap history, including gaps that can occur before a trade opens, before the +60s delayed candidate exists, or after that trade closes. The previous stop studies rejected any path with a non-empty gap list, so an old websocket gap could make later delayed-stop evidence look incomplete indefinitely.

The revised contract remains fail-closed for every gap that overlaps the candidate position interval and also requires at least one observed mark strictly after the delayed open. Non-causal historical gaps are ignored. No stop price, stop execution, delayed-entry fill, funding, risk, or paper-trading behavior changes.

**LIVE TRADING: DISABLED.**



### Exact research accounting follow-up — 2026-09-29

Two live research-only accounting failures are now handled without tolerances:

- fixed-schedule entry-filter portfolio timelines update running notional, planned risk, realized contribution, and exposure integrals with exact base-10 Decimal accumulation, so a flat cohort cannot end at a tiny negative residue after many high-precision opens/closes;
- delayed-entry contribution decomposition keeps the existing per-trade Decimal contract unchanged, but aggregate component sums now carry an explicit `decimal_rounding_residual_pnl` bridge instead of disabling the study when independent finite-precision paths differ by an ulp;
- the funding-corrected decomposition exposes matching component / legacy-bridge / candidate-bridge Decimal residuals;
- Issue #469 renders those residuals directly so Decimal bookkeeping cannot be mistaken for economic edge.

These changes affect research accounting and observability only. They do not change any trade, size, stop, fee, funding accrual, risk decision, execution path, readiness threshold, or live-order authority.

**LIVE TRADING: DISABLED.**


### Exact same-exit stop-validity accounting — 2026-09-29

The live delayed-entry stop-validity study exposed another research-only Decimal grouping failure after the broader accounting fix restored its upstream cohorts. Whole-cohort same-exit deltas and the stop-crossed/survived partitions were accumulated with ordinary Decimal addition, so high-precision values could differ by an ulp purely from grouping order.

The stop-validity summary now uses the shared exact base-10 accumulator for candidate PnL, actual PnL, deltas, partition totals, and absolute-PnL attribution. The existing per-trade Decimal contract is unchanged. Any aggregate candidate-versus-actual residual created by already-rounded per-trade deltas is surfaced explicitly as `candidate_actual_decimal_rounding_residual_pnl` instead of disabling the study.

The continuous-paper workflow now also watches the research modules in this runtime dependency chain, and a recursive workflow test fails if a future `continuous_paper.py` research dependency is not present in both bootstrap and graceful-handoff restart coverage.

These changes are research accounting, observability, and deployment-safety only. They do not change entries, exits, stops, sizes, funding, risk approval, readiness gates, promotion authority, or live-order behavior.

**LIVE TRADING: DISABLED.**

### Matched standalone overlap for the combined entry filter — 2026-09-29

The frozen top-10 + no LONG-trend candidate now publishes a second, explicitly descriptive view over the mature time window shared by its two standalone parent studies.

The overlap starts at the later of the standalone LONG+trend-filter start and top-10-rank-filter start. Every closed trade in that window must have both valid decision attribution and fresh opening-rank evidence before it can enter the matched cohort. The diagnostic then replays the exact frozen combined rule and reports allowed/blocked counts, contribution PnL, block-reason attribution, concentration/chronological robustness, and the same fixed observed-schedule portfolio view used elsewhere.

This overlap is not prospective evidence for the newer combined candidate. It always carries `fresh_combined_gate_credit = 0`, cannot change the combined readiness gate, and does not alter entries, scanner ranking, strategy decisions, risk, sizing, stops, exits, or live-order authority. Its purpose is to answer whether the two already-mature standalone signals reinforce each other on a clean shared cohort while the independent fresh combined gate continues collecting.

**LIVE TRADING: DISABLED.**

### Decision-time opening-opportunity evidence — 2026-09-29

The continuous-paper runtime now preserves every directional opening opportunity at the point where the baseline risk engine evaluates it, including opportunities that are rejected and therefore never produce an opening plan.

Each prospective record carries the exact original `RiskRequest`, instrument metadata, full visible L2 book consumed at the opportunity timestamp, baseline risk decision/reason, and the latest scanner rank snapshot available at that time. Records are content-addressed, conflict-detecting, stored inside durable continuous-paper state, and surfaced with approval/rejection/rank-completeness counts plus a state digest.

This capture exists to make future capacity-reflow research causal: if a filter removes an earlier trade and frees capacity, later replacement candidates can only come from opening opportunities that were actually observed with decision-time market and risk evidence. The capture itself does **not** model replacement trades, alter risk decisions, change entries, or grant promotion/execution authority.

**LIVE TRADING: DISABLED.**


### Opening-opportunity forward mark paths — 2026-09-29

Decision-time opening-opportunity evidence now has a durable post-decision market path. Every captured directional opportunity, including baseline risk rejections, is registered into a research-only forward-mark store. The continuous-paper worker advances those paths from the full native-market `metaAndAssetCtxs` snapshot on every context poll, not only from markets that remain in the selected websocket set.

The default path horizon is six hours with a two-minute completion-lag allowance. A path is complete only after the first real observed mark at or after that horizon; missing or late observations are not imputed. Path state is canonical, conflict-detecting, digestible, included in worker summaries/live telemetry, and preserved inside the exact continuous-paper state artifact across worker handoffs.

This closes a key evidence gap for future causal capacity-reflow work: a later opportunity that was rejected only because earlier baseline positions consumed capacity can now carry both its exact decision-time inputs and a real subsequently observed price path. This change still does **not** simulate replacement execution, choose an exit, claim counterfactual PnL, change risk decisions, or grant promotion/execution authority.

**LIVE TRADING: DISABLED.**


### Candidate capacity-reflow opportunity diagnostic — 2026-09-29

The continuous-paper dashboard now evaluates captured decision-time opening opportunities against the frozen `prospective-top10-no-long-trend-v1` rule before attempting any replacement-trade claim.

For baseline risk rejections with complete, fresh scanner-rank evidence, the diagnostic separates candidate-eligible opportunities from those the frozen rule would itself block. It then isolates aggregate-risk and correlation-bucket exhaustion and runs a one-position release sensitivity against the exact captured `RiskRequest`: each existing position is removed one at a time to test whether risk capacity would become positive. Results include rejection-reason counts, candidate block reasons, release-option counts, and the markets/correlation buckets whose removal would restore capacity.

This is intentionally narrower than a portfolio counterfactual. It does not assert that the released position would itself have been filtered, does not simulate a replacement fill or exit, and does not calculate replacement PnL. Its purpose is to identify real observed opportunities where capacity is demonstrably the binding obstacle so the next causal replay layer can focus on evidence-backed replacements.

**LIVE TRADING: DISABLED.**

### Candidate-filtered capacity release lineage — 2026-09-29

The capacity-reflow diagnostic now traces every one-position release option back to the exact historical opening plan that created the position consuming risk capacity. That plan is joined to its persisted decision fact and opening scanner-rank evidence, then evaluated under the same frozen `prospective-top10-no-long-trend-v1` rule.

A release now earns the stronger `candidate_capacity_release_opportunities` classification only when the observed later opportunity passes the frozen candidate, removing the historical position restores aggregate/bucket risk capacity, and the historical position itself is one the candidate would have blocked. The live diagnostic also reports lineage, plan, decision, rank, and stale-rank misses so unresolved joins cannot silently count as causal evidence.

This still stops before replacement execution. It does not assume the later opportunity would fill, does not reuse baseline portfolio state as a full counterfactual, does not choose a replacement exit, and does not calculate replacement PnL. It narrows the next replay stage to evidence-backed cases where the candidate can be shown to have freed the required capacity.

**LIVE TRADING: DISABLED.**

### Candidate daily-loss lockout reflow — 2026-09-29

Live decision-time evidence showed that the current rejected-opportunity cohort is dominated by `daily_loss_lockout`, so the next causal diagnostic now reconstructs how the frozen `prospective-top10-no-long-trend-v1` filter would change same-day realized cash before each rejected opportunity.

The captured `RiskRequest.account_state.daily_realized_pnl` remains authoritative. For candidate-eligible daily-loss rejections, the study finds closed trades from the same UTC accounting day that were fully opened and closed before the opportunity, attributes those trades using their persisted decision facts and opening scanner ranks, and removes the exact net PnL contribution of trades the frozen candidate would have blocked. It then compares the adjusted daily realized PnL with the exact captured daily-loss threshold.

An `exact_candidate_unlock_opportunities` count is granted only when the captured daily realized PnL reconciles exactly to the fully same-day closed-trade cash ledger, trade attribution is complete, and the opportunity has neither cross-day closed trades nor open positions whose same-day cash effects would require additional replay. Reconciliation misses, cross-day effects, and open-position effects are reported explicitly rather than estimated. Replacement entries, fills, exits, and replacement PnL remain unmodeled.

**LIVE TRADING: DISABLED.**


### Exact cross-day cash for daily-loss reflow — 2026-09-29

The daily-loss lockout reflow now reconstructs current-day cash for closed trades that opened before the UTC accounting day. It does not reuse whole-trade net PnL for those trades. Instead, it loads immutable exit fills for every recorded exit plan, revalidates fill lineage and aggregate realized PnL/fees against the journal, and adds only funding accruals whose verified boundary falls inside the current accounting day before the rejected opportunity.

This removes the main ambiguity in the current live cohort: cross-day trades can now participate in exact baseline daily-cash reconciliation and candidate-blocked cash removal without charging prior-day entry fees or prior-day funding to the current day. Exact unlock credit still requires complete candidate attribution, exact cash reconciliation, and no open-position cash effects at the opportunity timestamp.

Replacement entries, fills, exits, and replacement PnL remain unmodeled. **LIVE TRADING: DISABLED.**


### Durable UTC paper-account day rollover — 2026-09-29

Live daily-loss reflow evidence exposed an execution-accounting defect: the paper accounting model implemented `roll_account_day()`, but the replay/runtime path never invoked it. As a result, `daily_realized_pnl` and `day_start_equity` could remain anchored to an earlier UTC day and cause a false `daily_loss_lockout` after losses that should no longer count toward the current-day guard.

The paper execution adapter now performs a durable UTC-day rollover exactly once when the first replay record for a new day arrives. The rollover is persisted before the decision engine sees that record, resets only `daily_realized_pnl`, advances `day_start_ms`, and snapshots the account's current equity as `day_start_equity`; cash, positions, cumulative realized PnL, fees, funding, and loss-streak state are preserved. A persistence failure leaves the prior account untouched and degrades execution health rather than continuing with a partially rolled state. Funding is assigned to the daily risk ledger by its economic funding boundary: a late prior-day accrual still updates cumulative cash/funding but cannot leak into the new day's `daily_realized_pnl`, and a new-day accrual is rejected unless the account day has already rolled.

The live heartbeat now exposes `day_start_ms`, `day_start_equity`, and `daily_realized_pnl` so rollover behavior is directly auditable after worker handoff. This corrects paper risk accounting and can change future paper risk approvals that were previously rejected by a stale daily-loss ledger. It does not enable live orders.

**LIVE TRADING: DISABLED.**


### Candidate-caused replacement entry fill shadow — 2026-09-29

The capacity-reflow study now advances from “the frozen candidate would have freed capacity” to a research-only replacement-entry execution check. Only release options whose historical position lineage is complete and whose original entry the frozen `prospective-top10-no-long-trend-v1` rule would have blocked can enter this shadow.

For a same-UTC-day release position, the shadow loads its immutable decision-time paper-position history and removes its exact realized gross PnL, fees, funding, unrealized PnL, marked notional, planned risk, and reserved margin from the captured baseline account. Every other baseline position is deliberately held fixed rather than re-sized, so this is a single-release sensitivity and not yet a full candidate-portfolio counterfactual. The rolling seven-day peak is bounded conservatively so the weekly-drawdown veto cannot become artificially easier. The resulting counterfactual `RiskRequest` is sent through the production risk engine, the production opening-order planner, and the production IOC simulator using the exact instrument metadata and full L2 book captured at the original opportunity.

The shadow reports risk approvals, planning approvals, full/partial/no-fill outcomes, simulated entry notional, and entry fees. It fails closed on execution-configuration drift, incomplete historical position state, cross-day release positions, or lineage mismatches. It does not choose a replacement exit, does not calculate replacement-trade PnL, does not change the frozen candidate, and grants no promotion or execution authority.

**LIVE TRADING: DISABLED.**


### Exact daily-loss unlock lineage — 2026-09-29

The daily-loss reflow now exposes deterministic opportunity-level lineage in addition to aggregate counts. For every candidate-eligible lockout it records the exact opening-opportunity ID, candidate-adjusted daily realized PnL, captured daily-loss threshold, and candidate-blocked cash removed by the reconstruction. Separate ID sets identify closed-trade-adjusted unlocks, exact cash-scope opportunities, and exact candidate unlocks.

This is the handoff contract for later replacement-entry research: downstream execution simulation can consume only opportunity IDs that the exact cash model actually unlocked instead of reconstructing or broadening the cohort independently. It adds no execution authority and does not yet claim that an unlocked opportunity passes every remaining risk veto, would fill, or would be profitable.

**LIVE TRADING: DISABLED.**


### Replacement-entry fill lineage — 2026-09-29

The candidate-caused capacity-release fill shadow now exposes deterministic option-level execution lineage instead of only aggregate counts. Every simulated release option carries a stable composite option ID, the exact opening-opportunity ID and timestamp, opportunity market/direction, released position market/bucket/opening plan, the frozen candidate block reason for that released position, and the counterfactual equity adjustment used before risk evaluation.

The record then follows the production path explicitly: risk approval plus reason codes, opening-plan approval or planning rejection, and the exact IOC attempt outcome. Filled options retain requested/filled/unfilled quantity, average fill price, gross fill notional, taker fee, and immutable attempt ID. Separate fillable option/opportunity ID sets provide a strict join contract for forward-path markout research. Duplicate opportunity/release pairs fail closed rather than being counted twice.

This still models entry feasibility only. It does not choose replacement exits, calculate replacement PnL, alter the frozen candidate, grant promotion authority, or enable live orders.

**LIVE TRADING: DISABLED.**


### Candidate replacement forward markouts — 2026-09-29

The candidate-caused replacement-entry shadow now joins each simulated full or partial IOC fill to the durable observed forward path for the exact opening-opportunity ID. Fixed research horizons are 5 minutes, 15 minutes, 1 hour, and 6 hours. At each horizon the study uses the first real market mark at or after the target only when it arrives within a two-minute observation-lag bound; missing paths remain missing, horizons that have not matured remain pending, and late observations are labeled stale rather than imputed.

Each settled observation reports directional return, gross mark-to-market PnL, and entry-fee-adjusted mark-to-market PnL using the exact simulated fill quantity and average entry price. The output preserves option, opportunity, release-position, and IOC-attempt lineage so later research cannot broaden or duplicate the cohort independently.

These are fixed-horizon mark-to-market observations, not exits. No synthetic exit fill, exit fee, realized replacement PnL, promotion authority, or live-order authority is introduced.

**LIVE TRADING: DISABLED.**


### Account-day provenance for lockout evidence — 2026-09-29

The paper risk snapshot now carries the persisted account's exact UTC `day_start_ms` alongside `day_start_equity` and `daily_realized_pnl`. New opening-opportunity records preserve that value inside their exact `RiskRequest`, while legacy durable records remain readable with the field absent.

The daily-loss reflow now separates frozen-rule eligibility from causal eligibility. A rule-eligible lockout can enter cash-reflow analysis only when its captured account-day start exists and exactly matches the UTC day containing the opportunity. Legacy records without account-day provenance and records with a mismatched day are quarantined, counted explicitly, and cannot contribute adjusted-unlock or exact-unlock evidence.

This closes the evidence leak exposed by the earlier UTC-day rollover defect: historical lockouts captured with stale day state remain useful as documented historical observations, but they cannot be interpreted as evidence that the candidate would have causally reopened trading. New post-fix opportunities can earn causal credit only from verified day-state snapshots.

**LIVE TRADING: DISABLED.**


### Candidate replacement forward excursion and giveback — 2026-09-29

The candidate-caused replacement fill study now measures the observed path inside each settled fixed-horizon markout window, not only the endpoint. For every fillable replacement option it joins the exact simulated entry to the durable opening-opportunity mark path and reports the best and worst entry-fee-adjusted mark-to-market observations, their timestamps, time-to-best/time-to-worst, ending mark-to-market PnL, and peak-to-end giveback.

The aggregate view reports how often a replacement reached a positive mark-to-market peak, how often the horizon ended negative, and how often an observed positive peak reversed to a negative endpoint. This directly tests the decay visible in the current cohort, where short-horizon markouts have been stronger than the one-hour endpoint.

The study still uses observed periodic marks rather than synthetic exits. It does not infer intraminute extrema, does not create an exit fill or exit fee, and does not claim realized replacement-trade PnL. Its purpose is to determine whether the replacement opportunity is absent, persistently weak, or briefly favorable and later given back before choosing any exit hypothesis.

**LIVE TRADING: DISABLED.**


### Replacement exit horizon L2 evidence — 2026-09-29

The continuous-paper runtime now prospectively schedules real Hyperliquid L2 book captures for every newly observed directional opening opportunity at the same 5-minute, 15-minute, 1-hour, and 6-hour horizons used by the replacement forward-markout study.

The capture protocol is durable and explicitly non-retroactive. An opportunity can register only after the protocol start timestamp, so current liquidity can never be substituted for a missed historical exit book. On each 60-second context cycle, only horizons currently due are queried; a book is accepted only from the correct market and only when its receive timestamp is at or after the target and no more than 120 seconds late. Each accepted record preserves the real L2 depth plus the exit-time instrument size/leverage/minimum-notional metadata, with canonical conflict detection and a durable state digest across paper-worker rotations.

This evidence is a prerequisite for executable replacement-exit research. The next replay layer can use the captured book to simulate a reduce-only exit against real spread and visible depth instead of treating a mark price as a fill. Historical horizons that were not captured remain missing. No replacement exit, realized replacement PnL, promotion authority, or live order is created by this capture layer.

**LIVE TRADING: DISABLED.**


### Replacement fixed-horizon L2 exit fills — 2026-09-29

The candidate-caused replacement study now takes the next step beyond mark-to-market endpoints: when a real exit-horizon L2 book has been prospectively captured, it reconstructs the exact simulated replacement entry as a paper position and runs the production reduce-only planner plus IOC depth simulator against that captured exit book.

The replay preserves the replacement opening plan/risk/strategy lineage, entry fill quantity and fees, correlation bucket, venue leverage, and the exact paper execution config used for the entry. At each 5-minute, 15-minute, 1-hour, or 6-hour horizon it uses the executable top-of-book side as the exit reference, applies the normal 250ms paper latency and 25 bps IOC envelope, consumes only visible depth, and reports complete-position/partial/no-fill/rejected outcomes, exit fees, fee-adjusted realized PnL on the quantity actually closed, and any unclosed residual. The fixed horizons are alternative exit policies, so their economics are never summed into a synthetic cross-horizon PnL.

Funding remains deliberately unmodeled in this layer, so the reported entry/exit fee-adjusted economics are not yet a complete replacement-trade realized PnL claim. Missing exit books remain missing and are never synthesized or backfilled. This remains research-only and cannot authorize execution or promotion.

**LIVE TRADING: DISABLED.**


### Heartbeat-independent paper runtime upgrade watchdog — 2026-09-29

The continuous-paper workflow now has a second graceful-upgrade detector that does not depend on the trader emitting a heartbeat. Once per minute, the running job checks the repository's continuous-paper workflow queue for a newer main-branch push run. Because that workflow is path-filtered to runtime dependencies, a newer waiting push run is treated as an explicit signal that newer paper runtime code needs the concurrency slot.

When such a run exists, the watchdog touches the same durable graceful-stop file already consumed by the paper runtime. It does not cancel the job, kill the trader, bypass state upload, or enable live execution. The existing heartbeat-time source diff remains as a redundant fast path. This closes the handoff deadlock where a stale heartbeat could prevent the old worker from noticing that its replacement was already waiting.

**LIVE TRADING: DISABLED.**


### Exact zero-funding replacement realized PnL — 2026-09-29

The replacement-exit research now has a narrow path to exact realized PnL without inventing funding. For each simulated fixed-horizon exit, the study applies the same hourly funding-boundary convention as the paper execution engine: funding can apply at boundaries in the interval `(entry_attempt_ms, exit_attempt_ms]`.

An option-horizon receives exact realized-PnL credit only when the real-L2 reduce-only exit fully flattens the replacement position and that interval crosses zero funding boundaries. In that case funding is exactly zero by construction, so the existing entry/exit fee-adjusted close PnL is complete for that option-horizon. A partial close, a missing/rejected exit, or a complete close that crosses even one hourly boundary remains incomplete until exact funding evidence is available. A close exactly on an hourly boundary requires funding evidence; an entry exactly on a boundary does not owe that boundary.

Alternative 5-minute, 15-minute, 1-hour, and 6-hour exit policies remain economically separate and are never summed into a synthetic strategy PnL. This layer reports exact option-horizon PnL only; it does not claim a complete portfolio counterfactual, strategy-level realized PnL, promotion authority, or execution authority.

**LIVE TRADING: DISABLED.**


### Prospective replacement funding-boundary evidence — 2026-09-29

Replacement-entry and fixed-horizon exit replay can now collect the exact market inputs needed to price hourly funding for hypothetical replacement positions without weakening the paper execution freshness rules.

Every newly observed opening opportunity is registered prospectively for hourly funding boundaries through the longest replacement-exit window. Near each required hour, a dedicated collector polls the native market registry and retains only real oracle observations received at or before the boundary and within the same maximum asset-context age used by paper execution. After the boundary, the runtime fetches public funding history, requires the rate to canonicalize to that exact hour, and persists the oracle/rate pair with source, receipt timestamps, freshness, protocol start, and a durable state digest. Missing windows are counted as missed rather than backfilled.

This layer is evidence capture only. It does not yet add funding cash to replacement PnL, aggregate alternative exit horizons, alter the frozen candidate, change risk decisions, or grant promotion/execution authority. A follow-on evaluator can consume only complete captured boundary evidence and use the same authoritative funding-cash formula as paper execution.

**LIVE TRADING: DISABLED.**


### Exact funded replacement realized PnL — 2026-09-29

The fixed-horizon replacement-exit study now consumes the prospectively captured hourly funding-boundary evidence instead of stopping whenever an otherwise complete replacement close crosses a funding hour.

For every fully closed replacement option-horizon, the evaluator preserves the exact replacement market, direction, filled entry quantity, entry attempt timestamp, and real-L2 exit result. It enumerates the same hourly funding boundaries used by paper execution, requires a captured oracle/rate pair for every crossed boundary, and applies the production `funding_cash_delta` formula with the preserved signed quantity. The resulting funding cash is added to the already fee-adjusted entry/exit PnL. Zero-boundary intervals remain exact with zero funding by construction.

The evaluator fails closed: missing funding evidence leaves that option-horizon incomplete, duplicate funding evidence is rejected, alternative exit horizons remain economically separate, and no missing hour is estimated or backfilled. This produces exact option-horizon realized PnL only; it is not yet a complete portfolio counterfactual or strategy-level PnL claim and grants no promotion or execution authority.

**LIVE TRADING: DISABLED.**


### Prospective 5-minute replacement exit candidate — 2026-09-29

The replacement-trade research pipeline now freezes a single five-minute exit policy for prospective validation: `prospective-replacement-5m-real-l2-exit-v1`.

The five-minute horizon was nominated only from the pre-freeze discovery cohort, where the candidate-caused replacement markouts decayed materially between five minutes and one hour. That discovery cohort is explicitly excluded from this candidate's validation results. The durable state records its own start timestamp, survives paper-worker rotations, and only admits replacement opportunities observed at or after that freeze.

For admitted future opportunities, the policy uses the existing candidate-caused replacement entry simulation, the real captured L2 book at the fixed five-minute horizon, the normal reduce-only IOC execution model, and exact captured hourly funding evidence when a funding boundary is crossed. It reports only exact fully closed option-level realized PnL. Missing exit books, incomplete closes, or missing funding evidence remain incomplete rather than estimated.

Alternative horizons remain descriptive research and cannot be selected after outcomes are observed. This candidate has no strategy-level PnL claim, no promotion authority, and no execution authority.

**LIVE TRADING: DISABLED.**


### Prospective 5-minute replacement exit robustness — 2026-09-29

The frozen five-minute replacement-exit candidate now publishes a separate post-freeze robustness diagnostic over exact realized outcomes only.

The diagnostic reports exact-evidence coverage, gross profit/loss and profit factor, largest single-option contribution and share, leave-one-option-out PnL, market contribution concentration, leave-one-market-out PnL, and four chronological blocks. Incomplete outcomes remain excluded from economics but stay visible in the coverage count. A sample-size marker remains false until at least 30 exact post-freeze outcomes are available for review.

This module cannot change the fixed five-minute exit horizon, reuse the discovery cohort, grant promotion authority, or execute trades. It exists to prevent a positive aggregate result from being mistaken for durable evidence when that result is concentrated in one option, one market, or one time slice.

**LIVE TRADING: DISABLED.**


### Prospective 5-minute replacement exit review gate — 2026-09-29

The frozen five-minute replacement-exit candidate now has a precommitted review-readiness gate layered on top of its post-freeze exact-PnL robustness evidence.

The gate is intentionally fixed before the prospective sample matures. Review readiness requires at least 30 exact post-freeze replacement outcomes, positive aggregate exact realized PnL, profit factor above one, positive total PnL after removing any single option, positive total PnL after removing any single market, and all four full chronological blocks to remain positive. Unresolved leave-one-out or profit-factor evidence fails closed.

Passing this gate means only that the frozen candidate is ready for human review. It cannot alter the five-minute exit rule, cannot promote the candidate, and cannot authorize execution or live orders.

**LIVE TRADING: DISABLED.**


### Compressed packed continuous-paper handoffs — 2026-09-29

The durable continuous-paper state still uses the single packed tar artifact introduced for reliable file-count-independent handoffs, but the artifact transport now enables normal compression again.

The uncompressed packed artifact had grown to roughly 8.84 GB on the live worker even though the same underlying state had previously compressed to roughly 969 MB. That made exact predecessor restoration the dominant worker-rotation delay and pushed the artifact close to service size limits. The workflow now uploads the single tar with artifact compression level 6 and a 20-minute upload allowance, preserving the exact state contents and existing restore format while materially reducing network transfer size.

This changes only state transport. It does not prune research evidence, change paper accounting, alter strategy/risk/execution behavior, or enable live orders.

**LIVE TRADING: DISABLED.**


### Continuous-paper durable state size telemetry — 2026-09-29

The continuous-paper handoff workflow now measures the durable state before packing or uploading it. The diagnostic reports total logical and allocated bytes, total file count, a descending top-level store breakdown, and the largest individual files.

This was added after the exact paper state reached roughly 8.84 GB uncompressed. Transport compression fixes the network handoff cost, but it does not identify which durable research store is responsible for the on-disk footprint. The size manifest is intentionally read-only and runs before packing so its output remains available in the Actions log and step summary even if a later artifact transfer is slow.

The next lossless compaction step will be based on this measured breakdown rather than deleting or sampling evidence speculatively. No strategy, risk, paper-accounting, or execution behavior changes.

**LIVE TRADING: DISABLED.**


### Streamed packed-state restore — 2026-09-29

Packed continuous-paper artifacts are now restored without materializing both the artifact ZIP and the packed tar on the runner. For predecessor commits whose own workflow used the packed-state format, the restore path streams the trusted artifact through `funzip` directly into `tar` extraction under the state root.

The previous restore path could temporarily hold the roughly 8.84 GB artifact ZIP, another roughly 8.84 GB extracted tar, and the restored state at the same time. That multiplied peak disk usage during worker handoffs and could stall recovery before the trader restarted. Legacy multi-file artifacts remain supported through the existing unzip/copy path; packed-vs-legacy format is determined from the trusted predecessor commit's workflow rather than guessed from artifact size. Both restore modes are bounded by a 30-minute workflow timeout so a broken transfer cannot occupy the paper concurrency slot indefinitely.

The streamed restore is transport-only. It preserves the exact predecessor state, does not prune evidence, and does not change strategy, risk, accounting, execution authority, or live-order behavior.

**LIVE TRADING: DISABLED.**


### ZIP64-safe streamed paper-state restore — 2026-09-29

The packed continuous-paper artifact now restores through a dedicated single-member streaming ZIP decoder instead of Info-ZIP `funzip`. The live predecessor artifact exceeded 8 GiB and therefore used ZIP64 metadata; `funzip` interpreted the large member with legacy 32-bit length semantics and the downstream tar reader received invalid bytes. The new decoder reads the local member header directly, streams raw DEFLATE data with bounded memory, validates the member CRC, drains the remaining ZIP descriptor/central-directory bytes so the authenticated GitHub download can finish under `pipefail`, and requires the exact member name `continuous-paper-state.tar`.

Regression coverage forces ZIP64 even on a small fixture so the >4 GiB format path is exercised without creating multi-gigabyte test data. Legacy multi-file artifacts continue to use the existing unzip path. No durable evidence is pruned or approximated, and the decoder itself is included in both continuous-paper push-path and graceful-rotation dependency coverage.

**LIVE TRADING: DISABLED.**


### Interruptible research capture during paper-worker handoff — 2026-09-30

The continuous-paper runtime now honors an upgrade stop request inside the bounded research-capture loops that can otherwise extend a worker rotation after the top-level stop flag has already been raised. Due replacement exit-book requests, replacement-funding market requests, open-position funding refreshes, and replacement-funding oracle observation stop starting new work as soon as the handoff flag exists. The main loop also rechecks that flag after native-market refresh, after exit-book capture, after replacement-funding capture, and before the synchronous live-status research pass.

An already-started bounded HTTP request is allowed to finish and every evidence record already written remains durable. No evidence is pruned or partially rewritten, and this does not change strategy decisions, paper accounting, risk limits, promotion authority, execution authority, or live-order behavior.

**LIVE TRADING: DISABLED.**


### Stop-aware continuous-paper startup handoff — 2026-09-30

The continuous-paper startup path now honors an already-requested runtime handoff before starting each remaining market warmup and before the initial heavyweight live-status research render. If a newer main runtime arrives while a worker is restoring or starting, the worker still restores exact durable state and persists a checkpoint, but stops starting additional warmup work and skips the initial research render so it can reach the normal graceful-exit path sooner.

This complements the stop-aware steady-state capture loops. In-flight bounded calls are not interrupted mid-write, and durable evidence already restored or recorded remains intact. No strategy, risk, paper-accounting, promotion, execution-authority, or live-order behavior changes.

**LIVE TRADING: DISABLED.**


### Side-neutral prospective trade-quality gate — 2026-09-30

The next paper-research slice improves trade selection without disabling LONG or SHORT.

Candidate: `prospective-top10-price-confirm-v1`.

Frozen prospective rule:

- apply the **same rule** to LONG and SHORT;
- require fresh opening scanner rank in the top 10;
- wait exactly 60 seconds and reuse the existing visible-book IOC shadow;
- admit only a full or partial delayed fill whose simulated average price is no worse than the immutable opening-plan reference;
- rank-above-10, worse-price, and genuine no-fill outcomes contribute zero;
- partial fills keep only the actually simulated filled quantity; no replacement trade is invented;
- exact rank, delayed-outcome, opening-plan, market, side, and trade lineage must reconcile.

The state start timestamp is created on the first continuous-paper worker that contains this candidate and is then durably restored across worker handoffs. Historical trades before that timestamp receive no validation credit.

The review gate requires 30 prospectively evaluated trades, at least 10 admitted and 10 skipped outcomes, at least 5 evaluated LONGs and 5 evaluated SHORTs, and zero missing/stale/lineage integrity defects. The heartbeat reports actual versus candidate closed-trade contribution and splits the same rule by direction for diagnosis only.

This is deliberately a quality gate rather than a direction ban. It does not change the active paper strategy, risk limits, actual order timing, actual paper fills, promotion authority, or live-order authority. A future review-ready result remains research evidence only.

**LIVE TRADING: DISABLED.**


### Purged cadence opportunity learning — 2026-09-30

Cocomelon now has a side-neutral opportunity learner over the durable cadence shadow, so research can learn from thousands of directional opportunities rather than waiting only for executed paper trades.

Model family: `hierarchical_grouped_mean_v1`.

For each cadence/horizon surface independently, the learner:

- keeps the final 100 chronological settled opportunities as validation;
- removes any training label whose forward-return window overlaps the first validation decision boundary;
- requires at least 300 remaining purged training rows;
- estimates after-cost mean forward return from direction, lead strategy, and frozen decision-score band;
- deterministically falls back to broader direction-aware groups when a specific group has fewer than 25 training observations;
- admits a validation opportunity only when its training-only estimated mean net return is positive;
- evaluates candidate contribution against taking every directional opportunity;
- requires both LONG and SHORT representation and admissions before a surface can development-qualify;
- requires positive admitted mean return across four chronological stability blocks.

The primary research surfaces are the unchanged 15-minute execution cadence evaluated at 15-minute and 1-hour forward horizons. The 5-minute surfaces remain diagnostic and do not change execution cadence.

This analysis is **touched development evidence** because the cadence archive already existed when the model was introduced. It may generate hypotheses and frozen future challengers, but it is not clean prospective promotion evidence. It never rewrites the active strategy, changes paper orders, changes risk limits, promotes a candidate, or grants live execution authority.

**LIVE TRADING: DISABLED.**


### Cadence opportunity cohort attribution — 2026-09-30

The purged cadence learner now reports the exact validation cohorts behind its admitted and skipped decisions.

Each cohort is keyed by:

- direction;
- lead strategy;
- frozen decision-score band;
- the training-only grouped-mean estimate used for admission;
- the estimate support count and fallback specificity;
- validation count, mean net return, and total net-return contribution.

Admitted cohorts are ordered by validation contribution; skipped cohorts are ordered from most negative validation contribution upward. This makes the development result auditable and allows future hypotheses to target a setup combination rather than disabling an entire direction.

These tables remain touched retrospective/development diagnostics. They may inform a newly frozen prospective candidate, but no cohort is promoted or applied to paper execution from this report alone.

**LIVE TRADING: DISABLED.**


### Cadence opportunity artifact audit — 2026-09-30

A standalone research audit path can now evaluate the cadence opportunity learner directly from an exact durable `cadence-shadow-state.json` snapshot:

`python scripts/evaluate_cadence_opportunity_learning.py <cadence-shadow-state.json>`

The loader verifies the cadence-state schema, reconstructs typed settled outcomes, rejects duplicate outcome identities, and then runs the same purged chronological learner used by continuous paper live status. It has no dependency on a running paper worker and grants no execution or promotion authority.

This is intended for reproducible handoff-artifact review and incident analysis when live-status publication is delayed. It does not mutate the durable state.

**LIVE TRADING: DISABLED.**


### Cadence opportunity robustness diagnostics — 2026-09-30

The exact handoff-state audit shows that the purged cadence learner is structurally reviewable but not development-qualified.

Primary 15-minute cadence findings from run `36694359628`:

- 15m → 15m: 607 purged training rows, 100 validation rows, only 5 admitted rows, admitted validation sum `-0.01979833086445153168627683349`; zero SHORT admissions; all four chronological stability blocks fail.
- 15m → 1h: 541 purged training rows, 100 validation rows, 32 admitted rows, admitted validation sum `0.05115679681488476627838235566` versus `-0.2507418357977606892700705526` for taking every validation opportunity; however all 32 admissions are LONG and only two of four chronological blocks are positive.
- The sole admitted 15m → 1h exact cohort is LONG / trend / score 80+, with training-only mean net return `0.0002074996153318252029940204788` over 126 rows and validation mean `0.001598649900465148946199448614` over 32 rows.

Because the promising 1-hour result is temporally unstable and one-sided, it is **not frozen as a prospective trading rule**.

A new offline robustness audit therefore decomposes admitted validation contribution by market and chronological block, reports absolute-contribution concentration, leave-one-market-out sums, and exact cohort market/block attribution. These diagnostics do not alter learner admissions, paper orders, risk, promotion state, or live authority.

**LIVE TRADING: DISABLED.**
### Operational heartbeat / research separation — 2026-09-30

Continuous paper live telemetry is now split by responsibility.

The trading hot path emits an **operational-only heartbeat** built from in-memory account state, open positions, execution health, decision/risk counters, the latest observation, and the bounded recent-trade buffer. It does not run cumulative research decompositions before WebSocket streaming starts or during each steady-state polling cycle.

Heavy research analytics remain reproducible from durable state and completed artifacts through exact-state audit scripts such as the cadence opportunity learner and robustness audits. This prevents growing research history from delaying market streaming, live-status freshness, or graceful runtime handoff.

This changes telemetry scheduling only. It does not change strategy decisions, paper execution, sizing, stops, risk limits, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### Direct cadence-shadow research artifact — 2026-09-30

The continuous paper workflow now publishes `cadence-shadow-state.json` as a dedicated research artifact in addition to the full durable paper-state archive.

Artifact name:

`continuous-paper-cadence-shadow-<run_id>-<run_attempt>`

The direct artifact preserves the exact cadence state already present inside the durable checkpoint, but avoids downloading and unpacking the multi-gigabyte paper/journal/facts state when a cadence learner or robustness audit only needs the ~3.6 MB cadence JSON.

The full durable state remains unchanged and authoritative for runtime recovery. The cadence artifact is read-only research convenience data and grants no execution or promotion authority.

**LIVE TRADING: DISABLED.**


### Regime-aware cadence opportunity learner — 2026-09-30

A second research-only cadence meta-labeler now joins each 15-minute directional shadow outcome to its immutable decision-time `LearningFeatureSnapshot`.

The first contextual model is intentionally low-dimensional. It adds only:

- trend regime (`up/down/mixed/unknown`);
- volatility regime (`low/normal/high/unknown`).

Its deterministic hierarchy starts with direction + lead strategy + score band + trend regime + volatility regime, then falls back through broader direction-aware groups when a cell has fewer than the frozen minimum support. Training/validation remain chronological, forward-label overlap is purged, and missing/mismatched/late feature snapshots fail closed.

The same side-neutral development gates remain in force: enough LONG and SHORT validation observations, enough LONG and SHORT admitted opportunities, positive after-cost admitted mean return, and positive chronological stability blocks.

This is designed to answer **when a setup should be taken**, rather than banning a direction. It remains touched development evidence and cannot alter paper orders, sizing, stops, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Confidence-aware cadence context learner — 2026-09-30

The regime-aware cadence learner exposed two specific development failure modes in the exact handoff-state audit:

- a LONG / trend / 80+ / up / low-volatility cell had 9 training rows with mean net return about -0.548%, but the older hard-fallback hierarchy ignored that local evidence because the cell had fewer than 25 rows and admitted it from a broader positive parent;
- a SHORT / trend / 70-<75 / down / low-volatility cell had 25 training rows with only a tiny positive mean (about +0.007%) and then lost in validation.

A new research-only challenger replaces hard positive-mean fallback with a **first-supported local confidence hurdle**:

- exact/contextual groups can become decision-bearing from 5 training observations;
- broader fallback groups still require 25 observations;
- once a supported local group exists, broader parents cannot override its sign;
- admission requires the training mean minus 1.28 standard errors to remain above zero;
- chronological purging, immutable decision-time feature lineage, and the same LONG/SHORT development gates remain unchanged.

This is still touched development evidence. The confidence hurdle is a model-selection experiment, not a calibrated probability statement, and it cannot alter paper orders, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Fixed shallow cadence tree challenger — 2026-09-30

The next touched-development challenger reuses Cocomelon's existing frozen shallow-tree capacity rather than hand-picking thresholds from the nine confidence-model validation admissions.

Model family: `cadence_fixed_shallow_tree_v1`.

Frozen capacity matches the existing learning cycle:

- max leaf nodes: 7;
- minimum samples per leaf: 100;
- learning rate: 0.05;
- max iterations: 100;
- L2 regularization: 1;
- early stopping disabled;
- deterministic random state 0;
- admit only when predicted **after-cost net return > 0**.

The feature registry is intentionally compact and pre-existing: direction, lead strategy, decision score, 5m/15m/1h returns, funding, open interest, trend regime, and volatility regime. Market identity is excluded to avoid coin memorization.

Training remains purged chronological history and validation remains the final 100 settled 15m→1h opportunities. The same LONG/SHORT admission minimums and chronological stability blocks remain required.

This is research-only touched development evidence. It cannot alter paper execution, sizing, stops, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Nested cadence-tree rank calibration — 2026-09-30

The fixed shallow cadence tree showed useful but miscalibrated ranking on the exact 15m→1h handoff dataset: three of four chronological validation blocks were positive, yet the highest predicted-return quintile lost money while the next quintile was positive.

A research-only nested calibrator now separates model fitting from admission calibration:

- the final 100 settled opportunities remain untouched outer validation;
- the purged outer training set reserves its final 120 opportunities as an inner chronological calibration window;
- labels whose forward horizon overlaps that inner calibration boundary are purged again;
- the fixed shallow tree is fit only on the remaining inner training rows;
- inner calibration predictions are converted to five rank bands relative to inner-training prediction ranks;
- a band is eligible only with at least 15 calibration rows and calibration mean minus 1 standard error above zero;
- the tree is then refit on all outer training rows, and outer-validation predictions are admitted only when their rank falls into an inner-selected band.

This is touched development evidence. The calibration window selects rank bands, but the outer final 100 opportunities never participate in band selection. The same LONG/SHORT admission and chronological stability gates remain required. No paper execution, sizing, stops, risk, promotion, or live authority changes.

**LIVE TRADING: DISABLED.**


### Walk-forward cadence confidence learner — 2026-09-30

Static grouped, regime, confidence, and shallow-tree challengers all showed some signal but failed full chronological stability. The common failure pattern is non-stationarity: contexts that were weak over the full training history can become useful later, and vice versa.

A new research-only walk-forward challenger therefore evaluates the final 100 settled 15m→1h opportunities sequentially.

For each evaluation decision:

- only outcomes with `target_end_ms < decision_boundary_ms` may enter history;
- the learner keeps at most the most recent 300 settled opportunities;
- it reuses the confidence-aware contextual hierarchy over direction, lead strategy, score band, trend regime, and volatility regime;
- a context is admitted only when its current settled-history lower bound remains positive;
- no future or overlapping forward label is available to the estimate;
- insufficiently supported contexts are skipped rather than rescued by future information.

The same side-neutral development gates remain: both LONG and SHORT must have enough evaluation observations and admissions, candidate after-cost mean must be positive, and every chronological stability block must pass.

This is touched walk-forward development evidence only. It does not alter active paper strategy, sizing, stops, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Frozen prospective cadence microstructure challenger — 2026-09-30

Decision-time coverage on the exact run-36694359628 cadence state is strong enough to support a richer **future-only** challenger without imputing sparse inputs:

- 541/541 purged development rows and 100/100 touched validation rows contain spread, bid depth, ask depth, book imbalance, book age, realized 15m volatility, 15m range expansion, 15m relative volume, mark/oracle dislocation, 5m/15m/1h returns, funding, and open interest;
- OI change and funding change are present on 529/541 development rows and 99/100 touched validation rows;
- coverage selection used feature availability only, not outcome labels.

The candidate `cadence_microstructure_tree_prospective_v1` keeps the already-frozen shallow-tree capacity (7 leaves, 100-row minimum leaves, learning rate 0.05, 100 iterations, L2=1, no early stopping, seed 0) and adds only established decision-time Cocomelon features. Market identity remains excluded.

To stop repeatedly tuning on the same touched final-100 outcomes, the evaluation contract is now prospective:

- prospective start: `2026-09-30T14:00:00Z` (`1790776800000` ms);
- frozen training may use only outcomes with `target_end_ms < prospective_start_ms`;
- only decisions with `boundary_ms >= prospective_start_ms` can count as prospective evidence;
- post-freeze labels cannot affect fitted predictions or admissions;
- at least 100 prospective settled opportunities, LONG and SHORT admissions, positive after-cost admitted mean return, and all chronological stability blocks are required before development qualification.

This remains research-only. It does not change active paper entries, exits, sizing, stops, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Small prospective research artifacts — 2026-09-30

The continuous paper workflow now publishes the immutable decision-time `learning-features` store as a dedicated research artifact alongside the cadence shadow JSON.

Observed state size before this change was about 6.7 MB logical for `learning-features` and about 3.6 MB for `cadence-shadow-state.json`, versus roughly 9 GB of total durable state. Future prospective trade-quality audits can therefore consume the two small research artifacts instead of unpacking the full recovery archive.

Artifact pattern:

`continuous-paper-learning-features-<run_id>-<run_attempt>`

This is artifact packaging only. It does not change feature capture, paper decisions, orders, risk, or live authority.


### Immutable prospective cadence training fingerprint — 2026-09-30

The prospective cadence microstructure challenger now uses an immutable pre-freeze training fingerprint instead of rebuilding training from each future paper state.

Frozen source:

- paper run: `36705233182`
- source head: `d1f73e7d6abacc446bfcf09fa0f93ab2cecb3a81`
- durable artifact ID: `11092470461`
- durable artifact SHA-256: `c66a9f1c35ec5c1c996e413d0639b202e25469b9f4a99cf18af4ab053f5e5eb9`
- freeze workflow run: `36724607840`
- freeze artifact ID: `11101439177`
- freeze artifact SHA-256: `f1b262c2c0904eb1bbe0aab6dd4f88734d9635fe28cd68747b343595495e4a89`
- frozen rows: `652`
- first frozen target end: `2026-09-26T21:30:00Z`
- last frozen target end: `2026-09-29T16:15:00Z`
- aggregate row/feature digest: `c1baa8a730980402d02b80f960afa249e6cb653392c64b887074cd9efb2034e4`

Future prospective audits select the exact historical prefix ending at the frozen last target time, recompute every outcome hash plus immutable feature-record SHA, and require the row count and aggregate digest to match. Later-arriving historical rows are ignored when they fall after the frozen training prefix; insertions or mutations inside the frozen prefix fail closed.

This strengthens research integrity only. It does not change active paper decisions, entries, exits, sizing, stops, risk, or live authority.

**LIVE TRADING: DISABLED.**


### Canonical prospective evidence status — 2026-09-30

Issue #674 is the dedicated status surface for the frozen prospective cadence microstructure challenger.

After every successfully completed continuous-paper campaign, the automatic prospective audit updates #674 with:

- exact source paper run and attempt;
- pinned evaluator SHA;
- immutable frozen-training digest;
- prospective settled row count versus the 100-row requirement;
- admitted/skipped counts;
- candidate after-cost net-return sum and mean;
- LONG and SHORT prospective/admitted counts and contribution;
- chronological stability-block results;
- development-qualification state.

If the source campaign does not expose both compact cadence and feature artifacts, the issue is updated to a blocked state rather than silently retaining stale evidence.

This publication path is research-only. It does not write Issue #469, does not dispatch trading workflows, and does not modify paper execution, strategy, sizing, stops, risk, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


### Frozen prospective cadence baseline comparator — 2026-09-30

A second future-only research model is frozen as a comparator for the richer microstructure challenger.

`cadence_fixed_shallow_tree_v1` uses the original 10-feature cadence tree: direction, lead strategy, score, 5m/15m/1h returns, funding, open interest, trend regime, and volatility regime.

It uses the **same immutable 652 training outcomes and feature records**, the same training digest `c1baa8a730980402d02b80f960afa249e6cb653392c64b887074cd9efb2034e4`, the same 15m→1h surface, the same `2026-09-30T14:00:00Z` prospective boundary, the same shallow-tree capacity, and the same side-neutral/stability qualification gates as the microstructure challenger.

This comparator was specified without inspecting any settled post-freeze 1h outcome. Its purpose is to measure the **incremental value of the added microstructure/tradeability features** prospectively, not to create another promotion path. No model receives execution or promotion authority from this comparison.

**LIVE TRADING: DISABLED.**
### Prospective side-conditioned 60s/120s delay — 2026-09-30

The exact handoff-state delayed-entry audit found a simpler, more robust timing signal than the setup classifiers tested so far.

Touched development evidence over 26 paired evaluable trades showed:

- always-60s fill-weighted same-exit contribution improved the same trades by about +8.39 PnL versus actual entry timing;
- always-120s improved them by about +16.00 PnL versus actual;
- 120s was better than 60s for LONGs by about +10.28 PnL, while 60s was better than 120s for SHORTs by about +3.84 PnL;
- the fixed rule **LONG → 120s, SHORT → 60s** improved the paired sample by about +19.84 PnL versus actual and +10.28 versus always-60s;
- its edge versus always-60s was positive in all four chronological blocks and remained positive after removing any one market;
- one chronological block was slightly worse than actual entry timing, so the touched sample is not promotion evidence and the candidate still had negative absolute contribution.

A new candidate, `long-120s-short-60s-v1`, is therefore frozen **prospectively** after these observations. Earlier delayed-entry outcomes receive zero validation credit.

Frozen rule:

- every LONG remains eligible, but its shadow entry uses the existing +120s visible-book IOC outcome;
- every SHORT remains eligible, but its shadow entry uses the existing +60s visible-book IOC outcome;
- full, partial, and genuine no-fill outcomes use the existing fill-weighted same-exit accounting;
- unfilled quantity contributes zero and is not replaced;
- both 60s and 120s outcomes must be causally evaluable for paired comparison;
- no market exception, score exception, side ban, delay sweep, or optimizer is permitted.

The durable candidate start timestamp is created by the first continuous-paper worker containing this rule and survives worker handoffs. Review readiness requires at least 30 prospective closed trades, 20 paired evaluable trades, at least 5 LONGs, at least 5 SHORTs, and clean state/journal/outcome lineage. Temporal and market robustness are descriptive and do not bypass that gate.

This candidate is research-only. It does not delay actual paper entries, alter quantity, stops, risk, strategy decisions, or grant promotion/live execution authority.

**LIVE TRADING: DISABLED.**
### Prospective cadence model A/B comparison — 2026-09-30

Issue #679 is the canonical future-only comparison surface for the frozen cadence microstructure challenger and the frozen shallow-tree baseline comparator.

The comparison workflow evaluates both models against the exact same compact cadence/feature artifacts from a completed continuous-paper campaign. Each model runs from its own immutable code SHA:

- microstructure challenger: `efde8803da35d16529157729c2080a1cd99f9a4a`;
- baseline comparator: `34acb37c2f06c53eb81fe298db63ce4093c8de7b`.

Before publishing any delta, the workflow requires the models to agree on prospective start, frozen training row count/digest, prospective row count, and exact decision IDs. It also verifies boundary, market, direction, and realized net return for every paired future row.

Published evidence includes:

- candidate after-cost contribution for each frozen model;
- microstructure-minus-baseline contribution;
- both-admit / microstructure-only / baseline-only / neither counts;
- realized contribution of each model's unique admissions.

This is a comparator only. Neither model gains execution or promotion authority from Issue #679, and no paper orders are changed by the comparison workflow.

**LIVE TRADING: DISABLED.**


### Canonical prospective side-conditioned timing evidence — 2026-09-30

Issue #682 is the canonical evidence surface for the frozen `long-120s-short-60s-v1` timing challenger.

Future continuous-paper campaigns publish a compact timing artifact containing only:

- `journal.sqlite3`;
- the +60s delayed-entry outcome state;
- the +120s delayed-entry outcome state;
- the durable prospective side-conditioned candidate state.

Artifact pattern:

`continuous-paper-side-conditioned-timing-<run_id>-<run_attempt>`

The automatic evaluator is pinned to candidate commit `31c73c809b2c6cce2d189c87715d4f9d7c18c290`. It cannot override the candidate start timestamp: the prospective boundary is read only from the durable candidate state created by the first worker containing the frozen rule.

After every successfully completed paper campaign, and hourly as a catch-up backstop, the research workflow updates Issue #682 with:

- exact source run and attempt;
- frozen evaluator SHA and candidate ID;
- prospective closed-trade and paired-evaluable counts;
- LONG and SHORT contribution;
- selected contribution versus actual timing and always-60s timing;
- missing/non-evaluable outcome counts and lineage mismatches;
- descriptive chronological and leave-one-market-out robustness;
- frozen review-readiness state.

If the compact artifact is unavailable, Issue #682 is explicitly marked blocked instead of retaining stale evidence.

This publication path is research-only. It does not change actual paper entry timing, strategy, sizing, stops, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Continuous-paper learning-source recovery fix — 2026-09-30

A control-plane defect was found in the continuous-paper learning follower/catch-up path.

The paper workflow now uploads the durable state as `continuous-paper-state.tar` inside the GitHub artifact zip, but the learning follower and catch-up detector still expected raw `learning-features/` and `opening-lineage/` directories at the artifact-zip root. As a result, recent successful paper workers could be skipped as "not lineage capable" and catch-up could fall back to an old worker. The stale-worker path then compared numeric GitHub run IDs and could fail with `trusted learning state is ahead of newest lineage-capable paper worker`.

The recovery path now uses a dedicated compact authenticated source artifact:

`continuous-paper-learning-source-<run_id>-<run_attempt>`

It contains only:

- `session-summary.json`;
- `journal.sqlite3`;
- `learning-features/`;
- `opening-lineage/`.

The normal evidence follower consumes this compact source directly. Catch-up discovers the newest successful main-branch paper run that actually published the compact source, rather than downloading and introspecting the multi-GB recovery artifact. If trusted learning state already references a different source, relative ordering is determined from the source runs' `created_at` timestamps instead of numeric run-ID comparison.

This repair is research/control-plane only. It does not change scanner decisions, entries, exits, sizing, stops, risk, paper execution, promotion authority, or live-order authority.

**LIVE TRADING: DISABLED.**


### Append-only prospective prediction ledger — 2026-09-30

The frozen cadence microstructure challenger now has a separate control-plane integrity layer for its future-only predictions.

Issue #687 is the canonical prediction-ledger surface. After each successful Prospective Cadence Microstructure Audit, the ledger workflow:

- consumes the immutable prospective report artifact;
- restores the most recent successful prediction ledger;
- requires every previously published row to remain exactly identical in decision ID, boundary, market, side, prediction, admission decision, and realized net return;
- rejects a prior row that disappears or changes;
- permits newly settled rows to appear later even when their decision boundary is older than the newest already-settled row;
- permits only set-append-only future evidence: prior rows may never disappear or change;
- publishes canonical row and ledger SHA-256 digests;
- fails closed and marks Issue #687 BLOCKED before returning a failed workflow if any invariant is violated.

The ledger is deliberately separate from the frozen model evaluator, so this integrity layer cannot alter model features, training, predictions, qualification rules, or the prospective boundary. It has no execution or promotion authority and cannot dispatch the paper trader.

**LIVE TRADING: DISABLED.**


### Append-only prospective cadence A/B ledger — 2026-09-30

Issue #690 is the canonical row-level integrity surface for the future-only comparison between:

- `cadence_microstructure_tree_prospective_v1`;
- `cadence_fixed_shallow_tree_v1`.

After each successful Prospective Cadence Model Comparison, the A/B ledger records the exact paired future row:

- decision ID, boundary, market, and direction;
- realized after-cost 1h net return;
- frozen microstructure prediction and admission decision;
- frozen baseline prediction and admission decision.

The workflow restores the last successful ledger and requires every previously published paired row to remain exactly identical. A prior row that disappears, changes either model prediction/admission, changes realized return, or drifts in frozen-training identity fails closed and marks Issue #690 BLOCKED before the workflow fails. Late-settling older future boundaries may append, matching the single-model prediction-ledger semantics.

This ledger is deliberately separate from both frozen evaluators. It cannot change either model, cannot choose a winner, and has no paper-execution or promotion authority.

**LIVE TRADING: DISABLED.**


### Prospective side-conditioned timing row ledger core — 2026-09-30

The frozen `long-120s-short-60s-v1` timing experiment now has a separate row-level ledger core.

For every future trade that is prospectively eligible and has causally evaluable +60s and +120s visible-book shadow outcomes, the extractor records:

- immutable trade ID, market, direction, open time, and close time;
- actual paper net PnL;
- +60s fill-weighted same-exit net PnL;
- +120s fill-weighted same-exit net PnL;
- frozen selected delay (LONG=120s, SHORT=60s);
- selected fill fraction and selected net PnL;
- selected delta versus actual timing and versus always-60s.

The append-only ledger rejects any previously published row that disappears or changes and rejects candidate-start/rule drift. Late-settling older trades may append when their paired timing outcomes become evaluable.

The publishing workflow is intentionally deferred until this extractor core is merged, so the workflow can be pinned to the exact immutable merge SHA.

This is research/control-plane only. It does not delay actual paper entries or change strategy, sizing, stops, risk, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


### Pinned prospective side-conditioned timing outcome ledger — 2026-09-30

Issue #692 is the canonical append-only row surface for the frozen `long-120s-short-60s-v1` timing challenger.

The publisher is pinned to immutable extractor SHA `c5861658158014b359d9e00a67be96f8ba42275e`. It resolves the exact successful timing-audit artifact, derives the exact source paper run/attempt, then consumes only that paper run's compact side-conditioned timing state.

For every causally evaluable future trade, the ledger preserves actual PnL, +60s and +120s fill-weighted same-exit PnL, selected side-conditioned delay/PnL/fill fraction, and deltas versus actual and always-60s. Every previously published row must remain identical. Missing/changed rows or candidate-rule/start drift fail closed; late-settling older trades may append.

The ledger uses safe TSV artifact-identity transport and publishes BLOCKED before failing on append-only drift.

This is research/control-plane only. It does not delay actual paper entries or change strategy, sizing, stops, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Aggregate prospective trade-quality readiness — 2026-09-30

Issue #695 is the canonical fail-closed readiness surface joining the three append-only future-evidence ledgers:

- Issue #687 / `cadence-microstructure-prospective-prediction-ledger-v1`;
- Issue #690 / `cadence-prospective-model-comparison-ledger-v1`;
- Issue #692 / `prospective-side-conditioned-timing-ledger-v1`.

The aggregate evaluator consumes ledger **artifacts**, not issue prose. It re-runs each ledger's canonical digest/schema validator, requires the cadence prediction ledger and A/B ledger to match exactly in frozen-training identity and every microstructure prediction/admission/realized row, and recomputes the frozen readiness thresholds from immutable rows.

Cadence readiness mirrors the existing prospective contract: at least 100 settled future rows, at least 20 admitted rows, at least 10 LONG and 10 SHORT future rows, at least 5 admitted LONGs and 5 admitted SHORTs, positive admitted after-cost mean return, and all four chronological stability blocks passing with at least three admissions each.

Timing readiness mirrors the frozen `long-120s-short-60s-v1` contract: at least 30 prospective closed trades, 20 paired-evaluable timing rows, at least 5 LONGs and 5 SHORTs, and clean missing-outcome/lineage integrity. Timing economics remain visible but do not add a new retrospective hurdle.

The workflow resolves the **latest completed** main-branch run for each ledger. If the newest completed ledger run failed, its artifact is missing/expired, or cross-ledger lineage drifts, Issue #695 is marked BLOCKED rather than falling back to stale successful evidence.

A `ready_for_review` result is evidence only. This aggregate gate cannot alter paper entries or timing, sizing, stops, risk, promotion state, or live execution authority.

**LIVE TRADING: DISABLED.**


### Prospective model parsimony gate — 2026-09-30

The frozen cadence microstructure challenger must now justify its extra complexity against the simpler frozen shallow-tree baseline before it can become **ready for review**.

This does not change either model, the prospective boundary, the 100-row sample requirement, or any paper behavior. It only tightens research interpretation:

- the microstructure challenger must first pass its existing standalone future-only quality gate;
- the A/B ledger must contain at least the same 100 paired prospective rows;
- microstructure admitted contribution must exceed baseline admitted contribution on those identical rows;
- incremental microstructure-minus-baseline contribution must be positive in at least 3 of 4 chronological blocks.

A profitable complex model that merely matches or inconsistently beats the simpler baseline remains collecting. This is a precommitted parsimony rule added while only 3 prospective rows exist.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Prospective timing economic readiness gate — 2026-09-30

The frozen LONG=120s / SHORT=60s timing evaluator remains immutable. Its descriptive economics are now enforced by the aggregate review-readiness layer **before the first prospective timing row exists**.

Counts and clean lineage are necessary but no longer sufficient. Timing can become ready for review only when:

- 30 prospective closed trades and 20 paired evaluable trades are present, with at least 5 LONG and 5 SHORT;
- selected timing has positive total net PnL;
- selected timing improves total PnL versus actual entries and versus always-60s;
- LONG and SHORT selected PnL are each positive and each improves versus actual entries;
- all 4 chronological blocks contain at least 5 paired trades and improve versus both actual and always-60s;
- selected-minus-60s contribution remains positive after removing any single market.

This only tightens evidence interpretation. It does not alter the frozen timing shadow or paper execution.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Fixed prospective stability windows — 2026-09-30

The aggregate prospective readiness layer now uses the **final frozen review windows from the first row onward**, rather than repartitioning whatever partial sample happens to exist.

- cadence quality blocks are permanently prospective rows 1–25, 26–50, 51–75, and 76–100;
- cadence microstructure-vs-baseline incremental blocks use those identical row windows;
- timing robustness blocks are permanently paired timing rows 1–5, 6–10, 11–15, and 16–20.

Partial blocks are reported as open/provisional. A block becomes closed only when its full frozen row range exists. Because final review requires every cadence/timing block to pass, a failed **closed** block cannot be repaired by later rows; the readiness manifest therefore exposes `gate_path_open=false` as soon as that happens.

This does not loosen or alter the final sample/economic gates and does not change either frozen candidate or paper execution. It makes interim evidence interpretable and allows an irrecoverably failed candidate to be retired without wasting the rest of its prospective sample.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Incremental A/B gate-path correction — 2026-09-30

The fixed-window readiness layer distinguishes the cadence/timing gates from the microstructure-vs-baseline parsimony gate.

Cadence quality and timing robustness require **all 4** frozen blocks to pass, so one failed closed block makes those candidate paths irrecoverable.

The A/B parsimony rule requires positive microstructure-minus-baseline contribution in **at least 3 of 4** frozen blocks. Therefore:

- 0 failed closed incremental blocks: path open;
- 1 failed closed incremental block: path still open;
- 2 or more failed closed incremental blocks: path irrecoverable.

The readiness manifest now publishes the failed incremental-block count and the maximum allowed count explicitly. This is control-plane interpretation only; neither frozen model, prediction, paper trade, nor execution authority changes.

**LIVE TRADING: DISABLED.**


### Prospective candidate lifecycle states — 2026-09-30

The aggregate future-evidence gate now distinguishes **collecting**, **review_ready**, and **failed_closed_block** for each frozen challenger.

A candidate becomes `failed_closed_block` only when its precommitted fixed-window requirements make recovery mathematically impossible:

- cadence microstructure: any failed closed standalone stability block, or more closed A/B failures than the 3-of-4 parsimony rule can tolerate;
- side-conditioned timing: any failed closed 5-trade timing block.

Weak interim totals, sparse side counts, or incomplete samples remain `collecting` because later prospective rows may still improve them.

The aggregate manifest reports lifecycle counts and uses `all_candidates_failed` only when every frozen candidate is irrecoverably failed. This is a research-state label only. It does not retire or replace a strategy automatically and carries no paper execution or promotion authority.

**LIVE TRADING: DISABLED.**


### Immutable prospective first-failure receipts — 2026-09-30

Issue #702 is the canonical first-failure surface for the frozen prospective trade-quality candidates.

A separate append-only workflow consumes the canonical `prospective-trade-quality-readiness.json` artifact. When a candidate first enters `failed_closed_block`, it writes one immutable self-hashed receipt containing:

- candidate identity and frozen prospective boundary/training identity;
- exact readiness workflow run and attempt where irrecoverability was first observed;
- irrecoverable failure components;
- the exact failed closed block snapshot;
- source prediction/comparison/timing ledger digests.

Later readiness runs may add the other candidate's first-failure receipt, but an existing receipt cannot be rewritten or erased. If a previously failed candidate appears to recover under the same frozen contract, receipt continuity fails closed and Issue #702 is marked BLOCKED.

Pre-lifecycle readiness artifacts are rejected rather than interpreted as "no failure". The workflow runs after successful readiness updates, on an hourly catch-up schedule, and can be manually pointed at an exact successful readiness run.

This is research/control-plane integrity only. It cannot replace candidates automatically and has no paper execution, timing, sizing, stop, risk, promotion, or live authority.

**LIVE TRADING: DISABLED.**


### Prospective cadence actual-trade overlap — 2026-09-30

A fourth, **non-gating** evidence stream now measures whether the frozen cadence microstructure challenger would have improved the future trades the paper strategy actually took.

The join is exact rather than heuristic:

- cadence prediction rows carry the immutable strategy `decision_id`;
- closed paper trades carry `strategy_decision_id`;
- a match is accepted only when those IDs are identical and market/direction also reconcile;
- duplicate decision-to-trade mappings, changed prior rows, disappeared prior matches, or PnL reconciliation drift fail closed.

For every matched future closed paper trade, the ledger records the candidate admission, actual paper PnL/R, exit reason, and candidate-minus-actual contribution. It separately reports:

- blocked losing-trade PnL avoided;
- blocked winning-trade PnL sacrificed;
- admitted winners and admitted losers;
- net avoided-loss minus sacrificed-win contribution;
- LONG and SHORT splits.

The ledger consumes the small `continuous-paper-learning-source-<run>-<attempt>` artifact and the canonical prospective prediction ledger, so it does not need the full durable recovery archive.

Issue #704 is the canonical status surface. This overlap stream is descriptive future evidence only and **does not change the frozen prospective readiness gate**, paper execution, strategy, sizing, stops, risk, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


## Actual-trade overlap robustness frontier — 2026-09-30

The frozen prospective cadence candidate now has a separate review-only robustness contract for exact overlap with future closed paper trades.

The diagnostic does not become overlap-review-ready until it has at least 30 exact matched closed trades, at least 10 admitted and 10 blocked trades, at least 5 matched trades per direction, and at least 2 admitted trades per direction. It requires positive candidate economics and positive improvement in both dollars and net R, where net R measures profit or loss relative to the risk carried by each trade. The improvement must also remain positive in both units after removing any single matched trade.

This protects the trade-selection research from treating a tiny sample, one unusually large avoided loss, or changing trade size as evidence of a durable improvement. The overlap contract is descriptive only and does not alter the frozen cadence readiness gate, paper execution, timing, sizing, stops, risk, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


### Residual loss-shape diagnostic — 2026-09-30

The allowed-cohort residual analyzer now separates surviving losses into entry-quality failures versus profit giveback.

For every residual cohort and every existing side/strategy/rank/market grouping, it reports:

- losses with complete versus missing/incomplete MFE evidence;
- losses that never reached +0.25R MFE;
- losses that reached +0.25R but stayed below +0.5R MFE;
- losses that reached at least +0.5R MFE before closing negative;
- losses that reached at least +1R MFE before closing negative;
- the PnL attached to each loss shape;
- the worst market and side×strategy clusters for never-worked losses and giveback losses.

This is descriptive only and does not change the frozen top-10 + no LONG-trend candidate, readiness gates, paper entries, stops, exits, sizing, risk, promotion state, or live authority. Its purpose is to keep future changes targeted: poor-entry losses should drive entry research, while profitable-then-losing trades should drive exit/profit-protection research instead of another broad entry veto.

**LIVE TRADING: DISABLED.**


### Residual profit-lock exact-path overlap — 2026-09-30

The frozen combined entry-screen allowed cohort is now cross-checked against the existing exact observed-path profit-lock counterfactuals.

For each frozen profit-lock rule, the diagnostic reports:

- allowed residual losses with and without complete exact-path outcomes;
- activations, triggers, and losses rescued to non-negative estimated PnL;
- actual versus candidate PnL and net-R contribution;
- giveback-loss and deep-giveback-loss trigger coverage and contribution delta;
- leave-one-loss-out robustness in both PnL and net R.

This closes an important attribution gap. A loss merely reaching +0.5R or +1R MFE is no longer treated as proof that a profit lock would have helped; the rule must actually activate and trigger on the recorded mark path after frozen costs. Missing or broken path evidence is reported explicitly and fails open for telemetry only.

The overlap is descriptive and research-only. It does not alter the combined entry-filter gate, profit-lock readiness gate, paper entries, exits, stops, sizing, risk, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


### Same-side stop re-entry attribution — 2026-09-30

Closed paper trades now include a direction-neutral re-entry diagnostic for a specific repeated-loss behavior: reopening the same market in the same direction after the most recent completed same-side trade closed as a losing mark stop.

The diagnostic is causal and descriptive:

- only a prior close that was already complete before the new opening can qualify;
- a winner, breakeven, non-stop exit, or first same-side trade resets the re-entry label;
- re-entry outcomes are grouped into fixed `0-5m`, `5-30m`, `30-120m`, and `120m+` gap buckets;
- fixed descriptive skip windows of `<=5m`, `<=30m`, and `<=120m` report blocked winners/losses, contribution delta, and leave-one-trade-out robustness;
- LONG and SHORT re-entry cohorts are reported separately so any future rule can remain direction-neutral unless evidence says otherwise.

This is research-only. No cooldown, veto, entry, exit, stop, sizing, risk, readiness, promotion, or live-execution behavior is changed by this diagnostic.

**LIVE TRADING: DISABLED.**


### Repeated losing-stop streak evidence — 2026-09-30

A direct read of the completed predecessor paper journal from worker run `36776912988` (compact learning-source artifact `11127078697`) provides 61 closed trades for retrospective attribution.

The time-cooldown hypothesis is not supported by that journal:

- 16 trades reopened the same market in the same direction after a prior losing mark-stop close;
- all 16 reopened more than two hours after the prior stop, so the fixed `<=5m`, `<=30m`, and `<=120m` descriptive skip windows would have changed zero historical trades.

The stronger repeated-loss pattern is prior stop depth rather than elapsed time:

- after exactly one prior consecutive same-side losing stop: 11 trades, 5 winners / 6 losers, +35.9364722210739215 net PnL;
- after at least two prior consecutive same-side losing stops: 5 trades, 0 winners / 5 losers, -54.411794794875 net PnL and -2.18609613581944 net R;
- removing any one of those five trades still leaves the descriptive avoided-loss contribution positive (minimum +33.059041189375 PnL);
- those five trades came from two markets: four ENA LONG attempts and one HBAR LONG attempt; removing either market still leaves positive avoided-loss contribution (minimum +10.912728899875 PnL).

This is retrospective same-sample evidence only. It does not justify a direction-specific rule, does not count toward any prospective gate, and has no execution authority. The runtime diagnostic now measures prior consecutive same-market/same-direction losing-stop depth as `0`, `1`, `2`, and `3+`, plus descriptive thresholds at `>=1`, `>=2`, and `>=3` with leave-one-trade-out and leave-one-market-out robustness.

**LIVE TRADING: DISABLED.**


### Frozen prospective two-strike stop filter — 2026-09-30

The touched 61-trade predecessor journal exposed a repeated same-market/same-direction losing-stop pattern, but that retrospective evidence receives **zero prospective credit**.

A new direction-neutral research-only challenger is frozen as `prospective-two-strike-same-side-stop-v1`:

- scope: same market + same direction, applied identically to LONG and SHORT;
- a strike is earned only when a **candidate-admitted** trade closes negative via `MARK_STOP_TRIGGERED`;
- after two candidate-admitted strikes on one market/direction key, the next observed opening for that key is skipped once and the candidate strike count resets to zero;
- the actual outcome of a candidate-blocked trade never updates candidate strike state;
- a candidate-admitted non-losing-stop close resets that key to zero;
- overlapping openings are evaluated only from closes known before each opening event;
- the candidate changes no real paper order and models no replacement trades.

Candidate freeze is durable across worker handoffs. Clean scoring starts only after a locked **six-hour embargo** from the first post-merge freeze timestamp. Restarts restore the original freeze; unreadable/tampered state starts a new freeze and therefore loses evidence instead of inheriting credit.

The precommitted review gate requires at least 30 prospective closed trades, 5 blocked trades, 10 admitted trades, 5 LONG closes, and 5 SHORT closes, plus positive PnL and net-R delta and positive leave-one-trade-out and leave-one-market-out robustness.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Compact exact trade-path export — 2026-09-30

Completed Continuous Mainnet Paper Trader runs now have a separate research export path for exact observed mark-path evidence.

The exporter:

- binds to one completed successful main-branch continuous-paper run and exact run attempt;
- resolves the exact durable `continuous-paper-state-<run>-<attempt>` artifact;
- streams `continuous-paper-state.tar` and extracts only `trade-paths` plus `session-summary.json`, avoiding a full multi-gigabyte state restore;
- verifies exported trade-path record count against the source session summary;
- emits a deterministic SHA-256 tree digest over the exported path records;
- publishes a compact `continuous-paper-exact-paths-<run>-<attempt>` artifact for exit/profit-protection research;
- runs independently of the live paper worker and has no execution or promotion authority.

The workflow bootstraps once when introduced and then follows successful Continuous Mainnet Paper Trader completions, so exact-path exit research no longer depends on downloading the full durable paper-state artifact.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Append-only two-strike prospective ledger — 2026-10-01

The frozen `prospective-two-strike-same-side-stop-v1` challenger now has a dedicated durable evidence path separate from the live paper worker.

The compact continuous-learning artifact carries the tiny `prospective-two-strike-stop-filter-state.json` freeze record alongside the paper journal. A separate workflow consumes only successful paper handoffs and writes an append-only trade-level ledger to Issue #715 and an immutable artifact.

Each post-embargo closed trade row records:

- trade identity, market, direction, open/close timestamps and exit reason;
- realized net PnL and net R;
- the candidate's prior same-market/same-direction strike count at the opening;
- the frozen ADMIT/BLOCK decision implied by the two-strike rule.

Previously published rows must remain identical. Candidate ID, freeze timestamp, six-hour clean-start boundary, embargo and rule metadata are locked across ledger updates. A missing historical row, changed historical row, altered source-artifact identity, or freeze/rule drift blocks the new ledger update instead of rewriting evidence.

Old compact artifacts that predate export of the two-strike state receive zero credit and publish a waiting status instead of reconstructing or guessing the original freeze.

The ledger mirrors the precommitted sample/economic/leave-one-trade/leave-one-market readiness diagnostics but has no authority to change paper orders, risk, stops, sizing, promotion, or live trading.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Candidate stack overlap diagnostic — 2026-10-01

The frozen combined entry selector and the frozen future-only two-strike stop filter now have a shared clean-overlap diagnostic starting at the later candidate start.

Every matched closed trade is placed into exactly one descriptive bucket:

- blocked by both candidates;
- blocked only by the combined selector;
- blocked only by the two-strike candidate;
- blocked by neither.

The report compares actual, combined-only, two-strike-only, and stacked trade-contribution PnL/net R. The key incremental quantity is the two-strike-only bucket: those are trades the new repeated-stop rule removes that the existing combined selector would still have taken. Its contribution is also stress-tested with the same trade/market robustness framework and split by LONG versus SHORT.

This overlap is descriptive only. It gives no fresh readiness credit to either candidate, does not combine their promotion gates, and does not change paper execution, entries, exits, sizing, stops, risk, or live authority.

**LIVE TRADING: DISABLED.**


### Append-only profit-lock execution shadow ledger — 2026-10-01

The visible-book profit-lock execution shadow now has a compact append-only evidence path separate from the multi-gigabyte paper recovery artifact.

Each completed paper worker exports `profit-lock-execution-shadow-state.json` inside the authenticated compact learning source. Issue #721 consumes that exact successful paper artifact and records immutable per-trade/per-rule execution-shadow outcomes, including activation, trigger, simulated full-close state, visible-book candidate economics, and source type.

The ledger locks the existing execution-shadow start timestamp, rule definitions, and paper execution configuration. Every outcome must reconcile to the matching journal trade by opening plan, market, side, realized PnL, and realized R. Previously published outcomes may not disappear or change, source artifact identity is exact, and lineage/orphan counters may not regress.

The pre-existing review-volume gate is unchanged: per rule, 30 economically evaluated trades, 15 activations, 10 triggers, and 10 fully simulated visible-book closes are required, with clean lineage/orphan counters. The ledger also reports PnL/net-R contribution plus leave-one-trade and leave-one-market robustness as descriptive economic diagnostics; those diagnostics do not grant promotion or execution authority.

This is research/control-plane only. It does not move actual paper stops, close positions, change entries, sizing, risk, or live-order authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Frozen prospective breakeven profit-lock challenger — 2026-10-01

The mature visible-book execution shadow selected one exit challenger for a new clean campaign: `prospective-breakeven-after-0_5r-v1`.

The selection evidence is **touched predecessor evidence only**. Before freeze, the existing `breakeven_after_0_5r` execution shadow reached 30 economically evaluated trades, 16 activations, 10 triggers and 10 simulated full visible-book closes, with positive PnL/net-R contribution and positive leave-one-trade / leave-one-market robustness. Those observations justify selecting the challenger, but they receive **zero** clean promotion credit.

The frozen challenger is unchanged from the observed shadow rule:

- activate after the position reaches `+0.5R`;
- candidate stop level is breakeven (`0R`);
- use the existing visible-book execution simulator and its frozen cost/execution semantics;
- apply the same rule to LONG and SHORT;
- no replacement entry logic and no other profit-lock rule is bundled into this candidate.

The paper worker now persists a dedicated immutable freeze state. First deployment establishes `frozen_at_ms`; clean scoring starts only after a locked six-hour embargo. Normal worker handoffs restore the same freeze. Missing pre-freeze state receives no backfill, and a reset state begins a new clean campaign rather than inheriting old credit.

Clean readiness is computed from the existing append-only profit-lock execution ledger plus the cumulative paper journal. It requires:

- at least 30 economically evaluated future trades;
- at least 15 activations, 10 triggers and 10 complete visible-book simulated closes;
- at least 5 evaluated LONG and 5 evaluated SHORT trades;
- no missing future outcome, orphan outcome, lineage mismatch, restored-position orphan or incomplete triggered close;
- positive candidate PnL and net R;
- positive candidate-minus-actual PnL and net-R delta;
- positive leave-one-trade and leave-one-market robustness in both PnL and net R.

Issue #724 is the clean readiness surface. `ready_for_review` remains non-promotional and grants no paper stop mutation by itself. Any later paper-only rollout is a separate decision after the clean gate passes; live promotion remains subject to every locked live gate and explicit authorization.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Frozen prospective zero-strike momentum-band entry challenger — 2026-10-01

The newest completed compact paper journal contains 69 touched closed trades. The repeated-stop challenger can only act after prior candidate-admitted losing stops, so the remaining research question is first/reset entry quality.

Retrospective feature attribution found one compact direction-normalized pattern worth a clean challenger:

- only evaluate a market/direction key while its candidate losing-stop strike count is zero;
- require direction-signed 1h return to be at least `+1.5%`;
- reject direction-signed day return above `+10%` as already too extended;
- after a candidate-admitted losing mark stop, the momentum-band screen steps aside until a candidate-admitted non-losing-stop close resets the key;
- a blocked actual trade never updates candidate strike state;
- LONG and SHORT use the identical signed rule.

On the touched 69-trade journal, the state-machine counterfactual blocked 50 trades and left 19 trades with +94.29 net PnL and +2.97 net R. The allowed LONG and SHORT cohorts were both positive, and the candidate result was positive in each of four chronological blocks. The two newest clean first-strike losses, ADA LONG and FET LONG, also fail this touched rule. These observations are **discovery evidence only** and receive zero clean credit.

The frozen research-only candidate is `prospective-zero-strike-momentum-band-v1`. It uses the immutable opening feature snapshot already attached to each paper trade. Missing or incomplete opening features fail open to ADMIT for paper safety but block clean review readiness.

First deployment establishes a durable freeze timestamp. Clean scoring begins only after a locked six-hour embargo. The precommitted review gate requires at least 30 future closed trades, 5 blocked, 10 admitted, 5 LONG and 5 SHORT closes, complete feature integrity, positive candidate PnL and net R, positive candidate-minus-actual PnL and net-R delta, and positive leave-one-trade / leave-one-market robustness.

This challenger does not change actual paper entries, exits, stops, sizing, risk, promotion state, or live authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Append-only momentum-band entry ledger — 2026-10-01

The frozen zero-strike momentum-band challenger now has a durable append-only evidence path bound to exact successful paper artifacts.

Each clean ledger row locks the matching closed paper trade and opening-plan identity together with the candidate prior-strike state, immutable feature-snapshot ID, canonical feature-record SHA when the feature was evaluated, signed 1h/day momentum values, candidate decision/reason, and realized PnL/net R.

The ledger only starts from a compact paper source that contains the original frozen momentum-band state. Older compact artifacts receive zero credit. Every update is tied to one exact successful main-branch paper run and the SHA-256 digest of its compact learning artifact.

Previously published rows may not disappear or change. Candidate ID, freeze timestamp, six-hour clean-start boundary, embargo, and frozen rule must remain identical. Evaluated feature records are content-bound, while missing/incomplete features remain explicit fail-open rows and keep clean readiness blocked.

Issue #728 is the durable status surface. The ledger mirrors the candidate’s precommitted sample, economics, feature-integrity, leave-one-trade, and leave-one-market diagnostics but cannot alter paper orders, entries, exits, stops, sizing, risk, promotion, or live authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Momentum incremental stack overlap — 2026-10-01

The prospective candidate-stack audit now measures the frozen zero-strike momentum-band challenger against the existing combined entry-screen + two-strike base stack on a common future-only start.

The extension separates closed trades into four descriptive cohorts:

- blocked by both the base stack and momentum;
- blocked only by the existing base stack;
- blocked only by momentum;
- blocked by neither.

Only the **momentum-only** cohort counts as incremental momentum evidence. The audit reports its realized PnL/net R, LONG/SHORT split, market split, and leave-one-trade / leave-one-market robustness. It also reports the full three-filter stack minus the existing base stack, so redundant momentum blocks cannot be mistaken for new edge.

All three decision maps must be present after the later clean start for integrity to be clean. Missing decisions reduce matched coverage instead of being guessed.

This overlap is descriptive only. It changes no candidate readiness gate, paper order, entry, exit, stop, sizing, risk, promotion state, or live authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**



### Frozen future-only consecutive-loss cooldown relaxation shadow — 2026-10-01

A live paper heartbeat exposed 14 strategy opportunities that were all rejected by the existing `consecutive_loss_cooldown` risk veto after the account reached three consecutive losses. That observation is **touched research evidence only** and receives zero clean review credit.

A new research-only shadow is frozen as `prospective-consecutive-loss-cooldown-relaxation-v1`.

The baseline risk rule remains unchanged: after at least three consecutive losses, the paper engine can reject new exposure for up to one hour after the most recent close. The shadow tests fixed shorter cooldown windows of 15, 30, and 45 minutes without changing real risk behavior.

For each clean future cooldown rejection, the shadow:

- first applies the existing top-10 + no-LONG-trend entry screen;
- changes only the cooldown timestamp so that the baseline cooldown is treated as expired;
- reruns the same conservative risk engine, so capacity, daily/weekly loss, existing-market, health, and other vetoes still apply;
- reruns the actual opening planner and decision-time IOC simulation against the captured L2 book;
- scores filled shadow entries on the already-recorded forward mark path at fixed 5-minute, 15-minute, and 1-hour horizons;
- reports entry-fee-adjusted mark-to-market contribution, LONG/SHORT cohorts, elapsed-since-loss buckets, and leave-one-opportunity / leave-one-market robustness for the 1-hour horizon.

The candidate is frozen behind a six-hour embargo. Pre-freeze and pre-embargo opportunities are counted only as touched evidence. State survives worker handoffs; unreadable or tampered state starts a fresh freeze and therefore loses evidence rather than inheriting credit.

This study does **not** model a replacement exit or realized trade PnL and cannot authorize a risk-limit change. Any future proposal to shorten the real cooldown must first survive fresh future evidence rather than rely on the 14 opportunities that motivated the study.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**Changes risk limits:** `false`  
**LIVE TRADING: DISABLED.**


### Append-only cooldown relaxation evidence ledger — 2026-10-01

The future-only consecutive-loss cooldown relaxation shadow now has a separate append-only evidence contract tracked in Issue #733.

The ledger binds every update to the exact compact paper artifact and locks the candidate freeze, six-hour clean start, fixed 15m/30m/45m relaxation windows, fixed 5m/15m/1h markout horizons, and rule metadata.

A filled shadow option is **not** made immutable while any fixed forward mark is still `pending` or `missing_path`. It can enter the permanent ledger only after every fixed horizon is either `settled` or definitively `stale`. Risk, planning, or execution rejections are terminal immediately. This prevents ordinary forward-path maturation from being misclassified as historical evidence drift.

Previously published terminal rows must remain equivalent after canonicalization. Freeze/rule/source-artifact drift blocks publication instead of rewriting history.

Before clean data exists, each fixed cooldown window has a precommitted evidence-review bar: at least 20 settled one-hour options, at least 5 LONG and 5 SHORT settled options, at least 4 markets, positive fee-adjusted one-hour PnL and size-normalized fee-adjusted directional return, and positive leave-one-option / leave-one-market robustness in both units. Passing this bar authorizes evidence review only; it does not authorize shortening the live or paper risk cooldown, and realized-exit evidence would still be required for such a proposal.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**Changes risk limits:** `false`  
**LIVE TRADING: DISABLED.**


### Common-start full entry + breakeven stack audit — 2026-10-01

The prospective research surface now includes one common-start matched-trade diagnostic for the candidate machine as a whole rather than judging entry and exit challengers in isolation.

The audit begins at the latest clean start across the frozen combined entry screen, two-strike repeated-stop filter, zero-strike momentum-band filter, and breakeven-after-0.5R exit challenger.

For every closed trade after that common start:

- the combined, two-strike, and momentum decision maps must all be present;
- if any entry candidate blocks the trade, the full-stack candidate contribution is zero and no exit credit is required;
- if the entry stack admits the trade, the exact visible-book breakeven execution-shadow outcome must exist and reconcile by trade, opening plan, market, direction, realized PnL, and realized R;
- missing or economically unevaluable breakeven outcomes remain explicit integrity misses and are never guessed;
- actual, entry-stack-only, and full entry+exit PnL/net-R contributions are reported on the same evaluable cohort;
- the incremental contribution from breakeven beyond the entry stack is reported separately;
- the full-stack delta is stress-tested with leave-one-trade and leave-one-market robustness and split by LONG/SHORT and market.

This is matched-trade contribution evidence only. It is not a portfolio counterfactual, models no replacement trades, changes no candidate readiness gate, and has no execution or promotion authority.

**LIVE TRADING: DISABLED.**


### Full entry-stack capacity reflow audit — 2026-10-01

The common-start entry stack now has a portfolio-capacity correction path instead of assuming every blocked trade simply disappears with no downstream effect.

The new audit is deliberately one-hop and conservative:

- replacement candidates must be opening opportunities that were actually observed and rejected by the real paper risk engine for aggregate or correlation-bucket capacity;
- the replacement opportunity must have complete, fresh rank evidence and must pass the frozen combined, two-strike, and zero-strike momentum entry rules at its own decision timestamp;
- a capacity release receives credit only when the occupied baseline position is proven by opening lineage and closed-trade identity to be one the same frozen entry stack would have blocked;
- missing feature evidence, stale or missing rank evidence, unresolved open release positions, and missing stack decision maps are explicit integrity misses rather than guessed;
- for proven releases, the existing captured risk request, account state, L2 book, execution config, and single-position removal accounting are reused to test conservative risk approval, order planning, and IOC replacement-entry fillability;
- fillable replacements are then evaluated against the already captured fixed-horizon exit books using the same paper execution model;
- fee-adjusted realized PnL becomes exact for a horizon only when the replacement fully closes and every crossed hourly funding boundary has complete captured funding evidence.

The audit does **not** recursively simulate a new alternate portfolio and never aggregates economics across exit horizons. Replacement-entry, replacement-exit, and funding failures are isolated by layer. It still does not claim strategy-level or complete portfolio PnL.

The output is written only at paper-worker completion as `prospective-full-stack-capacity-reflow-summary.json` and is included in the compact learning artifact.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Append-only exact full-stack reflow PnL ledger — 2026-10-01

The one-hop full entry-stack capacity-reflow audit now has a separate durable exact-economics ledger at Issue #738.

Only a replacement option at a fixed exit horizon becomes immutable when the replacement exit fully closes and every crossed hourly funding boundary has complete captured evidence. Missing exits, partial exits and missing funding evidence remain outside the immutable ledger and may mature in later paper artifacts.

Each exact row locks the replacement option identity, opportunity market/direction, entry fill price/quantity/notional, fixed exit horizon, funding-boundary lineage, funding cash PnL, exact realized PnL and exact realized return. Previously published exact rows must never disappear or change.

Economics remain strictly separated by horizon. No best-horizon selection and no cross-horizon aggregation are allowed. Each horizon has its own precommitted review bar: at least 20 exact option-horizons, at least 5 LONG, 5 SHORT and 4 markets, positive realized PnL and return, plus positive leave-one-option and leave-one-market robustness in both units.

Old compact paper sources that predate entry-notional/return normalization publish a waiting status and receive no ledger credit.

This is research-only evidence. It does not change paper entries, exits, capacity limits, risk, readiness of any frozen candidate, promotion state or live authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Append-only full entry-exit stack matched-trade ledger — 2026-10-01

The common-start combined entry screen + two-strike + momentum + exact breakeven stack now has a separate durable matched-trade ledger at Issue #740.

A closed trade becomes immutable only when its stack economics are terminal:

- an entry-blocked trade freezes immediately with candidate contribution of zero and no exit counterfactual;
- an entry-admitted trade freezes only after the breakeven execution outcome is economically evaluable;
- missing or unevaluable admitted exits remain pending and receive no immutable economic credit.

Every row is cross-checked against the compact paper journal for market, side, opening lineage, actual net PnL, actual net R and initial risk. Candidate net R must reconcile exactly with candidate PnL and the trade's frozen initial risk.

The campaign identity locks the common overlap start plus the individual combined, two-strike, momentum and breakeven clean starts. Published terminal rows may never disappear or change.

The precommitted evidence-review bar is deliberately stricter than "better than actual paper": at least 30 terminal trades, 5 entry-blocked, 10 entry-admitted, 5 LONG, 5 SHORT and 4 markets; zero pending closed trades; positive final-stack PnL and net R; positive improvement versus actual PnL and net R; and positive leave-one-trade and leave-one-market robustness for both the final stack itself and its improvement.

Replacement-trade economics remain separate in Issue #738. This ledger is matched-trade contribution only and does not claim a complete portfolio counterfactual.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Eligibility readiness cause telemetry — 2026-10-01

The paper runtime now preserves the scanner's granular eligibility causes through the operational heartbeat instead of collapsing every readiness failure into strategy-level `not_deep_ready` or `not_rankable`.

For both the cumulative worker session and the latest decision epoch, the status reports:

- evaluated market count;
- rankable market count;
- deep-ready market count;
- exact eligibility reason counts, including broad eligibility failures plus `missing_deep_data`, `stale_book`, `excessive_spread`, and `insufficient_depth`.

No eligibility threshold is loosened and no trade is admitted by this change. Its purpose is to distinguish healthy selectivity from degraded/stale/missing market data before entry research interprets a NO_TRADE cohort.

**LIVE TRADING: DISABLED.**


### Exact breakeven early-exit capacity reflow — 2026-10-01

The common-start full entry+exit stack now has a separate one-hop capacity audit for opportunities that could exist because the exact breakeven challenger closes an admitted position before the real paper trade closes.

Capacity is credited only at the exact simulated close **completion** timestamp, never at activation or trigger time. A release is eligible only when the position was admitted by the frozen entry stack, the breakeven execution shadow fully closed it through the visible-book IOC path, the real paper position was still open at the later observed capacity-rejected opportunity, and that later opportunity independently passes the frozen combined, two-strike and momentum entry rules.

The audit then reuses the existing captured risk request, account state, position history, L2 book, paper execution configuration, fixed-horizon exit books and exact funding evidence to test replacement entry fillability and exact option-horizon realized PnL. Missing rank/features, missing prospective decision maps, or missing exact breakeven outcomes remain explicit integrity misses; incomplete or not-yet-completed breakeven exits receive no release credit.

Entry-block capacity releases remain in the existing full entry-stack reflow audit. Early-exit releases are written separately as `prospective-full-stack-exit-capacity-reflow-summary.json` so the two causal mechanisms cannot be double-counted. The layer is one-hop only, never recursively simulates replacement occupancy, never aggregates alternative exit horizons, and does not claim a complete portfolio counterfactual.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**Changes readiness gates:** `false`  
**LIVE TRADING: DISABLED.**


### Overlap-safe deep-shortlist websocket rotation — 2026-10-01

The continuous paper runtime no longer tears down the active deep-data websocket pair before a refreshed shortlist has proven replacement coverage.

On a shortlist change:

- the current redundant websocket pair remains authoritative while a replacement pair starts in parallel;
- replacement startup gaps are suppressed until promotion so connection warmup cannot create false evidence gaps;
- each replacement lane must emit L2-book evidence for every desired deep-shortlist market before the replacement is considered ready;
- only after that full two-lane market coverage is proven does the runtime reconcile the scanner/pipeline to the new shortlist and retire the previous pair;
- if replacement readiness fails, the replacement pair is cancelled and the existing healthy pair remains active;
- overlapping old/new events are de-duplicated by canonical replay event key through a bounded in-session cache;
- the paper heartbeat reports duplicate drops plus rotation attempts, promotions and readiness failures.

This is a market-data continuity fix. It does not loosen eligibility, strategy, risk, sizing, stop, exit, promotion or live-order rules. Its purpose is to prevent shortlist refresh mechanics from manufacturing `missing_deep_data` or stale-book blind windows that can suppress otherwise valid paper opportunities and contaminate research cohorts.

**LIVE TRADING: DISABLED.**


### Consecutive-loss cooldown timing telemetry — 2026-10-01

The paper heartbeat now exposes the exact state behind the global consecutive-loss cooldown: current consecutive losses, configured strike threshold, last close timestamp, elapsed time since that close, remaining cooldown time, configured cooldown duration, active/expired state, and state consistency.

This is operational observability only. The baseline remains a one-hour cooldown after the third consecutive loss. No risk threshold, cooldown duration, entry rule, sizing rule, stop, exit, promotion state, or live authority is changed.

The timing is especially important for the clean cooldown-relaxation shadow because rejected opportunities can now be interpreted against the frozen 15m / 30m / 45m alternatives without inferring timing from unrelated trade history.

**LIVE TRADING: DISABLED.**


### Latest-epoch stale-book age telemetry — 2026-10-01

The continuous paper heartbeat now preserves exact book age for every latest-epoch market whose scanner eligibility failed with `stale_book`.

The status reports stale-age evidence coverage, min/median/max age, and the five worst stale markets. This distinguishes borderline freshness misses just over the scanner's existing 5-second deep-readiness limit from genuinely stalled market-data lanes.

This is observability only. The scanner freshness threshold, execution freshness threshold, shortlist selection, strategy, risk, sizing, stops, exits, promotion state, and live authority are unchanged.

**LIVE TRADING: DISABLED.**


### Momentum-band fast forward-markout audit — 2026-10-01

The frozen zero-strike momentum-band entry challenger now has a separate fast descriptive evidence path that does not wait for trades to close.

The audit starts at the common clean boundary across the existing combined entry screen, two-strike repeated-stop filter, and momentum-band challenger. It only evaluates opening opportunities that the real paper risk engine approved and that the existing combined + two-strike base stack would already allow. This isolates the momentum challenger’s incremental decision instead of crediting it for opportunities another rule already rejected.

For each eligible opportunity, the audit reuses the immutable decision-time feature snapshot and the already captured opening-opportunity mark path. It reports direction-signed forward returns at fixed 5-minute, 15-minute, and 1-hour horizons for momentum ADMIT versus BLOCK decisions, plus the ADMIT-minus-BLOCK mean-return spread and leave-one-opportunity / leave-one-market robustness.

Missing/stale rank, missing/incomplete momentum features, missing paths, pending horizons, and stale path marks remain explicit. No prices are guessed and no trade PnL, replacement trades, or alternate execution are invented.

This is an early diagnostic only. It cannot change the momentum challenger’s 30-closed-trade clean readiness gate, any other readiness gate, paper orders, entries, exits, stops, sizing, risk, promotion state, or live authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**Changes readiness gate:** `false`  
**LIVE TRADING: DISABLED.**


### Append-only momentum fast-markout evidence ledger — 2026-10-01

The frozen zero-strike momentum-band challenger now has a separate append-only fast evidence path in Issue #750 for its fixed 5-minute, 15-minute, and 1-hour forward markouts after the existing combined + two-strike base stack.

The ledger is bound to the exact authenticated compact paper artifact and the frozen momentum state. An opportunity becomes immutable only when all three fixed horizons are terminal: each horizon must be either settled from an on-time recorded mark or definitively stale. Pending and missing-path opportunities remain unfrozen so normal path maturation cannot be mistaken for historical evidence drift.

Previously published terminal opportunities may never disappear or change. Candidate identity, freeze, clean start, common stack start, frozen rule, fixed horizons, and maximum accepted mark lag are locked across updates. Each source run also records whether rank and feature integrity was clean; any integrity miss blocks the fast evidence from becoming review-ready.

The precommitted early evidence bar is evaluated separately at every fixed horizon: at least 20 settled opportunities, at least 5 momentum ADMIT and 5 momentum BLOCK observations, at least 5 LONG and 5 SHORT observations, at least 4 markets, positive mean directional return for ADMIT, negative mean directional return for BLOCK, positive ADMIT-minus-BLOCK mean spread, and positive leave-one-opportunity / leave-one-market spread robustness.

This is an early separation diagnostic only. It cannot change the momentum challenger's 30-closed-trade readiness gate, any paper order, entry, exit, stop, sizing, risk, promotion state, or live authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**Changes closed-trade readiness:** `false`  
**LIVE TRADING: DISABLED.**


### Stream-local L2 freshness recovery — 2026-10-01

A live paper decision epoch exposed a market-data failure mode that was safe but economically disabling: 18 rankable markets were simultaneously rejected as `stale_book`, each with the exact same 54,591 ms book age, while other websocket records continued to arrive and both shortlist rotations had reported ready.

The root architecture was that websocket freshness existed only as a reporting helper. Redundant failover reacted to disconnect gaps, but an individual L2 subscription could stop advancing while trades, candles, or asset-context traffic kept the websocket session alive. In that state the active L2 lane remained selected and fresher standby books could remain buffered. Rotation readiness also accepted the first L2 snapshot without checking its exchange-time age.

The paper runtime now keeps the 5,000 ms deep-book eligibility ceiling unchanged and adds fail-closed recovery around it:

- L2 lane health is measured from the Hyperliquid exchange timestamp, not merely local message receipt;
- when one lane's L2 stream exceeds the frozen eligibility age, that stream opens a lane-local stale gap and can fail over to the redundant lane without revoking unrelated streams on the same websocket;
- supervisor wakeups include the next L2 stale deadline, so a silent book is detected even while no message arrives;
- shortlist replacement readiness credits only L2 snapshots that are already within the same frozen 5,000 ms age ceiling at receipt;
- if every selected market is stale on both redundant lanes at a runtime health check, a fresh replacement supervisor pair is started and is promoted only after both new lanes prove fresh L2 for every selected market;
- stale-L2 recovery attempts, promotions, and readiness failures are exposed in the operational heartbeat.

No stale book is made tradable, no freshness threshold is widened, and no paper order is created from missing microstructure. This is a data-availability repair, not a strategy relaxation.

**LIVE TRADING: DISABLED.**


### Entry-filter economic readiness hardening — 2026-10-01

Prospective entry-filter review readiness now uses one shared economic standard across the combined top-10/no-LONG-trend screen, the two-strike same-side stop filter, and the zero-strike momentum-band filter.

A candidate can no longer become review-ready merely because it loses less than actual paper. The pre-existing frozen decision rules and prospective rows are unchanged, but review readiness now additionally requires:

- the candidate itself to have positive net PnL and positive net R;
- positive candidate-minus-actual improvement in both PnL and net R;
- candidate profitability to remain positive after removing any one trade;
- candidate profitability to remain positive after removing any one market;
- candidate-minus-actual improvement to remain positive after removing any one trade;
- candidate-minus-actual improvement to remain positive after removing any one market.

The combined entry screen previously had only sample/integrity readiness, while two-strike only required positive improvement. Momentum already required positive candidate economics, but now uses the same candidate-and-delta leave-one-out standard as the other filters.

This hardens evidence interpretation only. It does not change frozen entry decisions, historical rows, paper orders, sizing, stops, risk limits, candidate promotion authority, or live execution.

**LIVE TRADING: DISABLED.**


### Paper context freshness headroom — 2026-10-01

The continuous paper runtime showed a full-universe availability failure with `stale_context=20`, while stale-L2 age coverage and stale-L2 recovery attempts remained zero. The context producer was polling REST market context every 60 seconds while coarse eligibility rejects context older than 60 seconds. Normal scheduling and request latency therefore left no freshness margin.

The paper runtime now refreshes REST market context every **30 seconds** while preserving the existing **60-second stale-context rejection ceiling**. This changes data refresh cadence only; it does not loosen eligibility, L2 freshness, strategy, risk, sizing, stop, readiness, promotion, or live-order authority.

The operational success criterion is that future decision epochs regain rankable markets without changing the stale-context threshold.

**LIVE TRADING: DISABLED.**


### REST context response-time provenance — 2026-10-01

The paper context refresh path now timestamps `metaAndAssetCtxs` snapshots when the HTTP response is actually received, not before the request begins.

This removes artificial context aging from network latency and retry time. A slow but successful response can therefore no longer consume part of the existing 60-second freshness budget before its data even enters the replay pipeline.

The 30-second polling cadence and the 60-second stale-context rejection ceiling remain unchanged. No eligibility threshold, strategy rule, risk limit, sizing rule, stop, readiness gate, promotion state, or live-order authority is relaxed.

**LIVE TRADING: DISABLED.**


### Post-data-freshness paper cohort — 2026-10-01

Paper performance now has a fixed descriptive cohort starting at the first worker that contains the current market-data continuity/freshness fixes: worker run `36910111457`, head `d97774d790628555cbff891f5c5d68952f287e43`, started at `2026-10-01T18:52:41Z`.

The cohort boundary is **trade open time**, not close time. A position opened before that worker remains in the pre-cohort even if it closes later.

The boundary intentionally groups the paper-data fixes that materially changed input quality before a decision is made:

- stale-L2 lane and supervisor-group recovery without relaxing the existing 5-second freshness ceiling;
- funding-oracle context continuity across worker handoffs;
- REST market-context polling at 30 seconds while retaining the existing 60-second stale-context rejection ceiling;
- REST market-context provenance timestamped at response receipt rather than request start.

Heartbeat research telemetry now reports post-boundary W/L/PnL/net-R, LONG/SHORT splits, and exit-reason cohorts beside the pre-boundary aggregate. Ten post-boundary closes are required before the status labels the descriptive sample complete.

This cohort does **not** reset or alter any prospective candidate, does not change any readiness gate, and has no execution or promotion authority. Its purpose is attribution: distinguish strategy losses from losses generated under already-fixed market-data defects.

**LIVE TRADING: DISABLED.**


### L2 recovery readiness-drift fix — 2026-10-01

A live paper heartbeat on worker `36910111457` exposed a recovery blind spot: 16 rankable markets simultaneously failed deep readiness with `stale_book` at roughly 33.5 seconds of book age, while the redundant L2 group still reported zero recovery attempts. The following heartbeat also showed the selected watchlist collapse from 20 markets to the single pinned open-position market before any stale-L2 recovery attempt was recorded.

Two mechanisms combined:

1. the group-level recovery check depended only on each websocket supervisor's stale-stream clock. A reconnect can temporarily refresh the supervisor's subscription/message fallback clock before that lane has delivered any fresh L2 book, so two churning lanes can avoid being simultaneously classified stale even while the trading pipeline has no fresh deep book;
2. shortlist rotation ran before systemic L2 recovery, so degraded input could replace/shrink the unhealthy group before the recovery check observed it.

The paper runtime now treats a required market as unhealthy on a lane when either:

- the supervisor reports that market's L2 stream stale by exchange-time freshness; or
- that lane has not demonstrated a fresh L2 book for the market.

A required market counts toward systemic recovery only when it is unhealthy on **both** redundant lanes. The existing majority threshold remains unchanged, so a single inactive market cannot create reconnect churn. Open L2 disconnect gaps now also revoke lane readiness; readiness returns only after a fresh book is observed.

Systemic L2 health is now evaluated before shortlist rotation. If the current group is systemically unhealthy, recovery runs first and that cycle's shortlist refresh is deferred; the refresh remains due and is retried on the next healthy cycle. This prevents stale/degraded input from rewriting the selected universe before the data plane is repaired.

This changes data-plane recovery only. The existing 5-second book-freshness ceiling, scanner eligibility, strategy, sizing, risk, stops, exits, candidate gates, and live authority are unchanged.

**LIVE TRADING: DISABLED.**


### Paper L2 watchlist liquidity floor — 2026-10-01

A live worker on the current freshness/recovery stack exposed a second data-plane lock-in: after one shortlist rotation, the websocket watchlist fell to the single pinned open-position market while the prior decision epoch had evaluated 20 markets and found 16 coarse-rankable. Later five-minute refreshes did not expand the watchlist, leaving the decision engine unable to collect fresh deep books for markets that could otherwise become eligible again.

The paper watchlist is now decoupled from immediate coarse trading eligibility:

- coarse-ranked native markets remain first and unchanged;
- when the coarse ranker returns fewer markets than the configured deep watchlist limit, unused subscription slots are filled deterministically from valid native REST snapshots;
- fallback ordering uses 24-hour notional volume first, then mark-valued open interest, then canonical market name;
- snapshots with invalid/non-positive required prices, invalid volume, future receipt timestamps, or non-native DEX identity are not eligible for fallback padding;
- pinned open-position markets remain subscribed even when they sit outside the configured watchlist limit.

This changes **data subscription coverage only**. Fallback-padded markets still pass through the existing scanner eligibility, deep-readiness, strategy, sizing, risk, stop, exit, and execution gates before any paper opening can occur. No threshold is relaxed and no live authority is added.

**LIVE TRADING: DISABLED.**


### Fresh REST L2 reseed during systemic websocket staleness — 2026-10-01

The paper runtime can now reseed the decision pipeline from the venue's real mainnet REST `l2Book` endpoint when the active redundant websocket group is systemically unhealthy.

The reseed is deliberately conservative:

- it runs only inside the existing systemic L2 recovery path;
- systemic failure can be confirmed either by both redundant websocket lanes **or by a new decision epoch whose own eligibility evidence shows a majority of selected books stale**;
- a pipeline-evidence trigger is consumed at most once per decision boundary, preventing repeated reconnect/reseed churn from one stale epoch;
- it requests only selected markets implicated by the websocket or decision-pipeline stale evidence;
- every REST response is normalized through the existing real-L2 normalizer;
- the book must pass the **same existing max-book-age freshness ceiling** used for websocket replacement readiness or it is discarded;
- accepted snapshots are recorded as real `hyperliquid-mainnet-info` L2 evidence and pass through the same replay/paper pipeline;
- REST reseeding does **not** mark either websocket lane healthy and does not replace the existing redundant-lane recovery; websocket replacement still runs immediately afterward;
- reseed cycles, accepted fresh books, and failed/stale responses are exposed in the operational heartbeat.

This addresses a failure mode where the decision engine can have zero deep-ready markets while the websocket control plane is recovering. It does not relax eligibility, spread, depth, risk, stop, sizing, strategy, or live-order thresholds and does not fabricate microstructure.

**LIVE TRADING: DISABLED.**


### Fast exact paper-worker resume path — 2026-10-01

The continuous paper handoff now has an optional fast-resume lane for the large durable runtime state.

The predecessor still produces the existing full durable state artifact unchanged. In addition, after trading stops and the final state is measured, it can create a precompressed `continuous-paper-resume.tar.zst` artifact containing the same state tree. Exact successors prefer that artifact and fall back automatically to the existing durable state artifact when the fast artifact is absent or unavailable.

Exact handoff workers use a source-run-specific concurrency key, so a successor may restore the already-finalized state while its predecessor continues uploading research and long-retention artifacts. Scheduled and push watchdog runs remain in the guarded concurrency lane and still self-skip when a real paper worker is active. The predecessor has already stopped the trading runtime before the fast successor is dispatched, so this optimization does not permit overlapping paper execution.

The fast pack/upload/dispatch path is non-authoritative and failure-tolerant. Any fast-path failure leaves the existing durable upload and fallback successor dispatch intact.

This changes no strategy, risk, sizing, entry, exit, stop, candidate readiness, paper accounting, promotion, or live-order authority.

**LIVE TRADING: DISABLED.**


### Clean candidate evidence runway diagnostic — 2026-10-01

The paper status now explains why a frozen prospective candidate may still have zero immutable closed-trade evidence after its clean start.

For the combined entry screen, two-strike stop filter, zero-strike momentum-band filter, and their latest common start, the diagnostic reports:

- directional opening opportunities observed after the relevant clean start;
- LONG/SHORT opportunity split and market breadth;
- baseline risk approvals, rejections, and exact rejection-reason counts;
- actual paper openings captured by durable opening lineage;
- closed versus still-open paper trades;
- realized PnL/net R for closed trades after the clean start;
- opening-lineage integrity and age of the oldest still-open clean opening.

The status assigns one descriptive stage: waiting for a directional opportunity, risk-rejected, approved without an opening, openings waiting to close, or closed-trade evidence available.

This is an evidence-starvation diagnostic only. It does not loosen strategy, risk, execution, candidate readiness, promotion, or live-order gates, and it is not an immutable economic ledger.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**LIVE TRADING: DISABLED.**


### Full entry-stack fast forward-markout diagnostic — 2026-10-01

The frozen combined + two-strike + momentum entry stack now has a separate fast descriptive evidence path that does not wait for paper trades to close.

The diagnostic starts at the latest clean start across the three frozen entry candidates. It evaluates only observed opening opportunities that the baseline paper risk engine approved, then applies the existing frozen stack in order:

- combined top-10 / no-LONG-trend screen;
- two-strike same-market/same-direction stop filter;
- zero-strike momentum-band filter.

Each opportunity receives one final stack decision, `ADMIT` or `BLOCK`, plus the first blocking layer. No threshold is refit and no new model is introduced.

Using the already captured opening-opportunity mark paths, the audit measures direction-signed returns at fixed 5-minute, 15-minute and 60-minute horizons. Per horizon it compares final-stack ADMIT versus BLOCK mean return, market breadth, LONG/SHORT coverage, and ADMIT-minus-BLOCK separation. Separation is stress-tested by removing any one opportunity and any one market.

A descriptive early-review flag requires at least 20 settled opportunities, at least 5 ADMIT and 5 BLOCK observations, at least 5 LONG and 5 SHORT observations, at least 4 markets, positive ADMIT mean, negative BLOCK mean, positive spread, and positive leave-one-opportunity / leave-one-market spread robustness.

This is an acceleration layer for learning whether the **surviving entry stack** is directionally useful before enough positions close. It does not change the existing closed-trade readiness gates, paper entries, exits, stops, sizing, risk, promotion state, or live authority.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**Changes closed-trade readiness:** `false`  
**LIVE TRADING: DISABLED.**


### Late decision-epoch stale-L2 recovery hardening — 2026-10-01

Worker run `36933148500` exposed a control-loop race after the latest L2 recovery changes. A completed decision epoch reported 20 evaluated markets, 16 rankable markets rejected for `stale_book`, and 16 matching stale-book age observations at about 8.8 seconds, while runtime recovery/reseed counters remained zero across multiple later heartbeats.

The pure recovery planner already recognizes that exact 16-of-20 pattern as systemic. The remaining gap was sequencing: WebSocket processing can finish a decision epoch after the control loop's first L2 health snapshot, while later asynchronous refresh/rotation work delays the next chance to act.

The runtime now centralizes systemic L2 recovery in one helper and checks it twice per control cycle:

- normal recovery check immediately after refreshed context/funding work;
- a second check after any shortlist warmup/rotation awaits and immediately before the operational heartbeat.

The existing decision-boundary deduplication remains authoritative, so the same pipeline stale epoch cannot trigger duplicate recovery. If the first check already recovered systemic L2, the late check is skipped.

This is market-data liveness hardening only. The 5-second deep-book eligibility threshold, strategy cadence, candidate rules, risk limits, execution model, and live-order authority are unchanged.

**LIVE TRADING: DISABLED.**


### Stale-L2 recovery across watchlist drift — 2026-10-02

The current paper worker exposed another stale-L2 recovery blind spot: the latest completed decision epoch can report a systemic stale-book majority while the selected watchlist changes before the control loop consumes that epoch.

The reason-count fallback previously required the latest epoch market count to exactly equal the current selected-market count. That equality is not a safety property; it is only a join convenience. During a shortlist handoff it can suppress recovery even when the completed epoch itself shows a clear systemic stale-book majority.

The recovery planner now evaluates the stale-book majority against the **completed decision epoch's own market count**. When that epoch is systemically stale but per-market stale keys cannot be joined safely to the current watchlist, the runtime conservatively recovers the current selected set. The existing decision-boundary deduplication, 5-second book-freshness ceiling, real REST L2 normalization, redundant websocket replacement readiness, strategy thresholds, risk limits, sizing, and execution semantics remain unchanged.

This is data-plane liveness hardening only. It does not make stale books tradable and does not add live-order authority.

**LIVE TRADING: DISABLED.**


### Venue-minimum rejection attribution — 2026-10-02

The paper capacity diagnostic now decomposes candidate-eligible `below_venue_min_notional` risk rejections instead of treating every sub-minimum order as one opaque failure.

For each observed opportunity that passes the frozen combined entry screen but is rejected because its safe notional is below the venue minimum, the audit recomputes the exact frozen risk and market caps from the captured decision-time request. It reports which safety ceiling is already below the venue minimum:

- target per-trade risk;
- aggregate/correlation-bucket risk capacity;
- gross-leverage capacity;
- available-margin capacity;
- visible-depth capacity.

It also reports total safe-notional shortfall and the extra planned risk that forcing the venue minimum would require. A minimum-notional rejection is never converted into an approval and the diagnostic exposes zero safe round-ups by construction: if every frozen cap could support the venue minimum, the baseline risk engine would not have emitted `below_venue_min_notional`.

This is attribution only. It does not raise order size, change risk-per-trade, loosen aggregate or bucket risk, widen leverage/margin/liquidity limits, alter candidate readiness, or add live-order authority.

**LIVE TRADING: DISABLED.**


### Point-in-time opening-rank lineage — 2026-10-02

The completed paper artifact from worker `36963189604` exposed 18 prospective opening opportunities after the full-stack clean start, but none could enter the full entry-stack markout cohort: 16 were baseline risk rejections and the remaining two risk-approved opportunities had missing coarse-rank lineage. The capacity-reflow audit independently showed nine capacity-rejected opportunities with missing rank evidence.

The root cause was an in-memory lineage race. Opening traces are stamped at the L2 event's decision-time timestamp, while the coarse-rank tracker previously retained only the newest context-refresh snapshot. If an older queued L2 event was processed after a newer context refresh, the only retained rank snapshot could be later than the opening timestamp, so the research sink correctly refused to attach future rank evidence even though a valid earlier snapshot had existed.

The coarse-rank tracker now retains a bounded history of the latest 64 canonical snapshots and resolves the newest snapshot that actually existed at or before the opening timestamp. It does not resurrect a market that was absent from that latest prior snapshot, and downstream rank-age gates remain unchanged.

This repairs evidence lineage only. Scanner ranks, entry decisions, risk approvals, order sizing, stops, exits, candidate rules, readiness gates, promotion state, and live authority are unchanged.

**LIVE TRADING: DISABLED.**


### Risk-rejected full-stack fast-markout shadow — 2026-10-02

The full entry-stack forward-markout audit now keeps a second, strictly descriptive cohort for strategy opportunities rejected by baseline risk.

This closes a current learning blind spot without weakening risk:

- risk-rejected opportunities are scored through the same frozen combined + two-strike + momentum entry stack;
- 5m / 15m / 60m directional markouts are recorded separately from risk-approved candidate rows;
- baseline risk reason codes are preserved, including lockouts such as `weekly_drawdown_lockout`;
- the shadow reports whether the frozen entry stack would itself ADMIT or BLOCK each rejected opportunity and the mean forward return by risk reason;
- missing rank or momentum evidence in this cohort has its own integrity counters and cannot contaminate the existing candidate readiness calculation.

This cohort has no readiness, promotion, sizing, risk-relaxation, order, or live authority. Its purpose is to answer whether a risk lockout is protecting the account from poor signals or merely suppressing otherwise good setups before any proposal to change that guard is considered.

**LIVE TRADING: DISABLED.**


### Append-only risk-rejected fast-markout ledger — 2026-10-02

The risk-rejected full-stack fast-markout shadow now has a separate append-only evidence surface on Issue #774.

Each successful paper handoff is bound to its exact compact learning artifact and contributes only risk-rejected opening-opportunity rows whose fixed 5m / 15m / 60m horizons are terminal. Pending or missing-path rows remain unfrozen until a later source makes them terminal.

The ledger preserves:

- exact baseline risk reason codes, including `weekly_drawdown_lockout`;
- frozen combined + two-strike + momentum stack decision and block layer;
- direction, market, strategy and point-in-time scanner rank lineage;
- terminal forward markouts and their lag status;
- cumulative reason-level means plus stack-admitted leave-one-opportunity and leave-one-market robustness.

Previously published terminal rows may not disappear or change after canonicalization. Source run/attempt and compact-artifact digest are recorded on every append. Metadata drift, source identity drift, or historical row mutation blocks the ledger update instead of rewriting evidence.

This ledger is descriptive only. It cannot relax risk, change candidate readiness, place paper orders, alter sizing, promote a candidate, or enable live trading.

**Execution authority:** `false`  
**Promotion authority:** `false`  
**Changes risk limits:** `false`  
**Changes candidate readiness:** `false`  
**LIVE TRADING: DISABLED.**


### Systemic missing-deep L2 recovery — 2026-10-02

The current paper worker exposed a cold-start L2 blind spot: 16 of 20 selected markets were rankable but reported `missing_deep_data`, leaving zero markets deep-ready after multiple context polls even though the redundant websocket supervisors had not raised stale-book recovery.

The pipeline recovery planner now treats a systemic latest-epoch `missing_deep_data` count as an L2 recovery condition, using the same majority threshold already used for systemic stale books. A systemic missing-deep epoch recovers the full selected watchlist through the existing REST L2 reseed path and redundant websocket-group replacement; the replacement group is promoted only after every selected market has fresh L2 on every lane.

Small/non-systemic missing-deep cohorts do not trigger recovery, and a decision boundary can trigger the fallback only once. This changes data recovery only; it does not relax deep-readiness, strategy, risk, sizing, or execution gates.

**LIVE TRADING: DISABLED.**


### Risk-rejected ledger source-format compatibility — 2026-10-02

The risk-rejected fast-markout ledger now distinguishes an authenticated compact paper artifact that predates the `risk_rejected_rows` export from a malformed current-format source.

A compact full-stack forward-markout summary is ledger-eligible only when it carries:

- `risk_rejected_rows` as a list;
- `risk_rejected_stack_evaluated` as an integer equal to the row count;
- `risk_rejected_integrity_clean` as a boolean.

Older authenticated summaries publish a waiting-for-new-format status and receive zero ledger credit. Current-format summaries still pass through the strict append-only ledger validator, where schema drift or immutable-row mutation fails closed.

This changes evidence-source compatibility only. It cannot alter risk vetoes, candidate readiness, execution, sizing, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


### Risk-rejected risk-budget investigation gate — 2026-10-02

The append-only risk-rejected fast-markout ledger now has a precommitted, review-only gate for deciding when a baseline risk reason has enough evidence to justify deeper risk-budget research.

The gate counts only opportunities that baseline risk rejected but the frozen combined + two-strike + momentum entry stack would **ADMIT**. Strategy-blocked opportunities cannot make a risk veto look unnecessarily conservative.

For each risk reason, all fixed 5m / 15m / 60m horizons must independently have:

- at least 12 settled stack-admitted rejected opportunities;
- at least 4 markets;
- at least 3 LONG and 3 SHORT opportunities;
- positive mean directional return;
- positive mean remaining after removing any one opportunity;
- positive mean remaining after removing any one market;
- clean cumulative source integrity.

Only then does that risk reason become `ready_for_risk_budget_investigation`. This is not permission to relax the risk rule. It only means there is enough diversified, robust forward evidence to investigate whether a safer alternative risk budget is worth designing and prospectively testing.

The gate is review-only and cannot change risk limits, candidate readiness, order sizing, execution, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


### Decision-epoch L2 recovery wakeup — 2026-10-02

Worker `36995939153` showed a completed decision epoch with 20 selected markets, 15 `stale_book` rejections, only one deep-ready market, and zero L2 recovery/reseed triggers even after repeated operational heartbeats. The pure recovery planner already classified that stale majority as systemic; the remaining failure was wakeup timing.

The continuous paper runtime now signals the control loop whenever a new decision epoch completes. The loop waits on that signal as well as its normal context-poll deadline, so a newly completed systemic stale/missing-deep epoch can trigger the existing REST L2 reseed and redundant websocket replacement immediately instead of waiting for the next 30-second context cycle. The normal REST context cadence is preserved, and the existing decision-boundary deduplication prevents repeated recovery from one epoch.

This changes data-plane liveness only. Book freshness limits, deep eligibility, strategy thresholds, risk vetoes, sizing, candidate readiness, execution semantics, promotion state, and live-order authority remain unchanged.

**LIVE TRADING: DISABLED.**


### Startup context freshness through warmup — 2026-10-02

The first heartbeat from fixed worker `37002459760` on `c4ae39f` showed that the stale-L2 race was no longer the immediate blocker, but startup had completed a decision epoch with `stale_context=20`. The initial mainnet context snapshot was fetched before per-market candle warmup, so a long warmup could consume the existing 60-second context freshness budget before live supervision began.

Startup now refreshes native mainnet market context during warmup whenever the normal 30-second context-poll interval elapses, and performs one final unconditional context refresh immediately after warmup. Each refresh preserves response-time provenance, updates rank lineage, forwards fresh selected-market context into the replay pipeline, and captures any due exit-book context.

The existing 60-second stale-context rejection ceiling is unchanged. No eligibility threshold, L2 freshness limit, strategy rule, risk limit, sizing rule, stop, readiness gate, promotion state, or live-order authority is relaxed.

**LIVE TRADING: DISABLED.**


### Decision-free startup bootstrap and heartbeat-independent handoff — 2026-10-02

The first implementation of startup context refresh (#780) refreshed the full native context repeatedly during candle warmup. Although it preserved freshness, the successor worker remained in startup far longer than the preceding worker and did not publish its first heartbeat on the prior startup timescale. That implementation is therefore superseded rather than accepted as an operational tradeoff.

Continuous paper startup now has an explicit decision-free bootstrap path. Initial selected-market snapshots and historical candle warmup records are applied to the replay state without scheduling or emitting strategy decision epochs. After warmup completes, the worker performs one fresh mainnet context refresh, updates rank lineage, feeds those fresh snapshots through the normal decision path, and only then starts the decision clock. This prevents a warmup-only stale-context epoch without repeated REST context polling during bootstrap.

The runtime handoff watchdog also no longer requires a newer push-triggered paper run to still be queued or running: a completed newer main-branch paper push run is sufficient evidence that runtime code changed. Push-triggered guard runs now remain alive for a short rendezvous window when another paper worker is active, so an older worker can request graceful handoff even before its first heartbeat.

Replay behavior is unchanged unless callers explicitly opt into decision-free bootstrap seeding. The 60-second context ceiling, book freshness, strategy rules, risk limits, sizing, stops, readiness, promotion state, and live-order authority remain unchanged.

**LIVE TRADING: DISABLED.**


### Fresh opening-book gate — 2026-10-02

Current worker `37007947897` recovered broad L2 usability to 14 deep-ready markets, but its session risk telemetry included two `stale_market_data` opening vetoes. The opening queue previously allowed a cached post-latency book to proceed to risk even when that book had aged beyond the execution freshness ceiling by the time the queue was evaluated.

The opening engine now keeps the candidate pending when its cached market book is older than the existing execution `max_book_age_ms` limit. The candidate is evaluated only after that same market supplies a fresh post-latency book. Canonical candidate ordering is preserved, and stale context/account/execution-health conditions still fail closed through the existing independent risk engine.

This does not widen book freshness, context freshness, risk budgets, sizing, stops, eligibility, strategy thresholds, or live authority.

**LIVE TRADING: DISABLED.**


### Operational L2 recovery telemetry repair — 2026-10-02

Issue #469 repeatedly displayed zero stale-L2 recovery/reseed counters while the continuous paper worker alternated between healthy deep coverage and systemic `stale_book` epochs. The detailed end-of-run heartbeat already carried the recovery counters, but the lightweight operational heartbeat used for the live issue omitted them. The renderer therefore displayed missing fields as zero.

The operational heartbeat now includes the same stale-L2 recovery attempts, promotions, readiness failures, REST reseed attempts/books/failures, and pipeline-trigger/fallback counters as the durable heartbeat. This repairs live observability only; it does not alter recovery behavior, market data thresholds, strategy, risk, sizing, execution, or live authority.

The next worker heartbeat can now distinguish “recovery never fired” from “recovery fired but did not keep books fresh through the next decision boundary.”

**LIVE TRADING: DISABLED.**


### Full entry-stack fast-markout append-only ledger — 2026-10-02

Issue #769 previously had only a placeholder status and no durable workflow, so the frozen combined + two-strike + momentum entry stack could emit 5m / 15m / 60m forward-markout summaries without accumulating immutable cross-run evidence.

The research path now has an append-only full-stack fast-markout ledger bound to authenticated compact paper artifacts. It accepts only baseline-risk-approved opportunity rows, validates the frozen combined / two-strike / momentum layer ordering from the persisted candidate states, freezes only rows whose fixed horizons are terminal, and preserves every previously published terminal row byte-for-byte.

Terminal horizons may be settled, stale beyond the fixed mark-lag ceiling, or explicitly unsupported by the persisted opportunity path. Pending and missing-path horizons remain unfrozen. Per-horizon review still requires at least 20 settled opportunities, 5 ADMIT, 5 BLOCK, 5 LONG, 5 SHORT, 4 markets, positive admitted mean, negative blocked mean, positive ADMIT-minus-BLOCK spread, and positive leave-one-opportunity / leave-one-market robustness.

A dedicated workflow now wakes from completed Continuous Mainnet Paper Trader runs, binds the exact source run / attempt / artifact digest, restores the previous immutable ledger, updates Issue #769, and uploads the next ledger artifact. Legacy compact sources that predate risk-approved full-stack row lineage wait without credit instead of failing or fabricating evidence.

This is research-only acceleration of entry-quality evidence. It changes no strategy threshold, risk veto, sizing, execution behavior, closed-trade readiness gate, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**

### Context refresh cannot be starved by L2 recovery — 2026-10-02

Worker `37023957344` demonstrated that the repaired L2 recovery path was active: 35 recovery attempts, 35 successful promotions, 700 fresh REST-reseeded books, and zero readiness failures. Its latest decision epoch nevertheless had `stale_context=20`, so fresh books were no longer the limiting input.

The control loop used a timestamp captured before event-driven L2 recovery to decide whether the periodic 30-second market-context poll was due. A recovery that crossed the poll deadline could therefore return to a stale pre-recovery timestamp, incorrectly take the early `continue`, and postpone context refresh again.

The loop now re-reads the clock immediately after L2 recovery before the context-due check. Recovery can no longer consume the remaining context freshness headroom while leaving the scheduler unaware that the refresh deadline has passed. Recovery heartbeats also use the refreshed post-recovery timestamp.

This changes scheduling correctness only. The 30-second context cadence, 60-second context freshness ceiling, L2 freshness limit, eligibility rules, strategy, risk, sizing, execution, readiness, promotion state, and live-order authority remain unchanged.

**LIVE TRADING: DISABLED.**



### Risk-rejected stack block-layer attribution — 2026-10-02

With market-data freshness restored, the active paper worker is again producing directional signals while the weekly drawdown lockout remains active. The risk-rejected fast-markout ledger already preserved each opportunity's frozen full-stack decision and blocking layer, but Issue #774 only summarized ADMIT versus BLOCK and risk reason. That made it impossible to see whether the combined filter, two-strike stop filter, or momentum band was responsible for rejecting the setups.

The ledger summary now derives terminal block-layer counts and, at each fixed 5m / 15m / 60m horizon, reports per-layer opportunity count, settled count, directional-return mean, sign counts, and market breadth. Existing immutable rows are unchanged, and validation explicitly accepts previously published summaries that predate this attribution.

This is descriptive entry-quality evidence only. It cannot relax risk, change entry-candidate readiness, alter sizing or execution, promote a strategy, or enable live trading.

**LIVE TRADING: DISABLED.**


### Combined-filter block-reason attribution — 2026-10-02

The risk-rejected stack attribution showed that the combined entry filter blocked five of the first eight terminal weekly-drawdown-locked opportunities, with positive mean directional returns at both 15m and 60m. That sample is too small to justify changing the filter, but it makes the combined layer the most important place to inspect for avoidable over-filtering.

The risk-rejected fast-markout ledger now breaks combined-layer blocks into the frozen rule's exact reasons: `long_trend`, `rank_above_10`, and `long_trend_and_rank_above_10`. For each fixed 5m / 15m / 60m horizon it reports opportunity count, settled count, directional-return mean, sign counts, and market breadth by combined reason.

Previously published immutable rows remain unchanged and older summaries remain valid. This is descriptive evidence only and cannot change the combined filter, risk limits, sizing, execution, readiness, promotion state, or live authority.

**LIVE TRADING: DISABLED.**

### Per-lane L2 supervisor diagnostics — 2026-10-02

The active continuous paper worker accumulated more than one hundred systemic L2 recovery attempts while still returning to a latest decision epoch with 16 stale books and zero deep-ready markets. REST reseeds were largely successful and replacement websocket groups were usually promoted, so recovery counters alone could not distinguish a subscription failure, reconnect churn, one-lane degradation, or post-promotion message loss.

Operational heartbeats now include a diagnostic snapshot for each redundant websocket lane: connection state, reconnect / duplicate / anomaly counters, last-server-message age, ready-market count, missing-ready markets, stale-L2 market count, and stale market identities. The live status also reports the cross-lane unhealthy-market count.

This is observability only. It does not change L2 freshness limits, websocket subscriptions, recovery thresholds, REST reseeding, strategy decisions, risk limits, sizing, execution behavior, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### L2 exchange-vs-receive skew telemetry — 2026-10-02

Per-lane L2 supervisor telemetry on worker `37053031783` showed both redundant WebSocket lanes connected with near-zero server-message age and no reconnect churn, yet both lanes reported `ready=0`, `stale=0`, and all 20 required markets missing readiness. This isolates the repeated stale-book recovery churn away from basic socket connectivity.

The operational heartbeat now records the latest L2 exchange-time minus receive-time relationship per required market and lane, including observed-market count, negative-age count, minimum/maximum exchange age, and the exact markets whose exchange timestamp is ahead of local receive time. This is diagnostic only: the existing freshness gate still rejects future-dated exchange timestamps, and no strategy, eligibility, risk, sizing, execution, promotion, or live-order rule changes.

The next runtime handoff will use this telemetry to distinguish venue/runner clock skew from genuinely stale or malformed L2 timestamps before any freshness semantics are changed.

**LIVE TRADING: DISABLED.**


### Pre-recovery L2 supervisor snapshot — 2026-10-02

The active paper worker repeatedly showed a decision epoch with 16 `stale_book` rejections while the post-recovery supervisor heartbeat showed both redundant websocket lanes fully connected, all 20 L2 markets ready, zero lane-level stale markets, zero reconnects, and sub-second exchange-to-receive age. Because that heartbeat was emitted after replacement promotion, it could not distinguish a genuinely unhealthy feed from a stale replay/pipeline view that triggered recovery while the live feeds were still healthy.

The runtime now captures the exact redundant-supervisor health snapshot immediately before every guarded stale-L2 recovery. The operational heartbeat records whether the trigger came from supervisor health, decision-pipeline evidence, or both; the supervisor-unhealthy and pipeline-stale market counts; the decision boundary; fallback state; and the full per-lane connected/readiness/staleness/reconnect/server-age/exchange-age snapshot from before reseed or replacement.

This is diagnostic-only. It does not change the 5-second L2 freshness ceiling, subscription topology, recovery trigger, REST reseed, websocket replacement, eligibility, strategy, risk, sizing, execution, readiness, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### Silent websocket self-reconnect — 2026-10-02

Pre-recovery telemetry from worker `37063325586` resolved the repeated stale-L2 churn. Immediately before guarded recovery, both redundant lanes still reported `connected=true` and all 20 markets had previously reached readiness, but every L2 stream was stale and neither lane had received any server message for roughly 70 seconds. The exchange-vs-receive age on each lane's last observed L2 snapshot remained sub-second, so clock skew was not the cause. The sockets were silently wedged while still appearing connected.

`WebSocketSupervisor` now supports an explicit server-message silence timeout. The continuous paper runtime pins that timeout to 15,000 ms. If a session receives no server message within that window, the supervisor treats the socket as failed, emits the existing disconnect gap semantics, closes it, reconnects with existing bounded backoff, and resubscribes. Each redundant lane can therefore heal independently before the 30-second outer paper control loop needs to rebuild the whole supervisor group.

The existing 5,000 ms deep-book freshness ceiling remains unchanged. This does not weaken eligibility, fabricate freshness, change recovery evidence, alter strategy/risk/sizing/execution rules, promote any candidate, or enable live orders.

**LIVE TRADING: DISABLED.**


### Record-pump stall timing telemetry — 2026-10-02

The current worker on `354324f` proves repeated L2 freshness loss is not explained by independent socket disconnects. Immediately before recovery both redundant lanes can remain connected with all 20 markets previously ready, zero reconnects, and more than 80 seconds since the last server message. The configured 15-second server-silence watchdog cannot fire if the supervisor coroutine is blocked downstream after receiving a message.

The continuous paper heartbeat now records the maximum shared record-pump processing duration, maximum wait for the pump lock, count of records taking at least one second, and the exact last slow record kind / event kind / market. This is diagnostic only and is intended to distinguish a slow pipeline record from lock contention before changing any WebSocket, replay, strategy, or risk behavior.

No data-freshness threshold, strategy rule, risk limit, sizing rule, execution behavior, readiness gate, promotion state, or live-order authority changes.

**LIVE TRADING: DISABLED.**


### Non-blocking continuous-paper checkpoint writes — 2026-10-02

Live telemetry on worker `37069124243` ruled out the shared record pump as the cause of repeated redundant-WebSocket stalls: the maximum record processing time remained below 10ms with zero lock wait, while both websocket lanes still stopped receiving server messages for roughly 85 seconds at the same time.

The runtime was still performing its full checkpoint synchronously on the asyncio event loop every 30 seconds. The predecessor's durable state artifact is approximately 1.3GB, so JSON serialization and atomic file replacement can monopolize the event loop long enough to prevent both socket lanes, the 15-second server-silence watchdog, and the 30-second context refresher from running.

Periodic runtime checkpoints now capture their state payloads on the event loop and hand JSON serialization / disk writes to a single background worker thread. Only one background checkpoint may be in flight; if the next cadence arrives while a write is still running, it is skipped rather than queued. The next checkpoint deadline is based on the current clock after scheduling, preventing catch-up checkpoint storms. Startup and final persistence remain synchronous because no live feed needs servicing at those boundaries.

Operational telemetry now reports maximum snapshot-build time, maximum background-write time, background checkpoint starts, and overlapping checkpoint skips. This preserves atomic per-file writes and exact final persistence while keeping live market-data servicing responsive.

No market-data freshness limit, strategy rule, risk limit, sizing rule, execution behavior, readiness gate, promotion state, or live-order authority changes.

**LIVE TRADING: DISABLED.**


### Event-loop stall attribution for L2 freezes — 2026-10-02

The latest continuous-paper diagnostics showed both redundant websocket lanes remaining logically connected and fully subscribed while receiving no server message for roughly 83–91 seconds. Exchange-vs-receive L2 age stayed normal when messages were present, record-pump processing stayed below 125ms, and the configured 15-second server-silence reconnect did not fire during the freeze. This demonstrates that the asyncio event loop itself is being blocked outside the record pump.

The runtime now runs a 250ms event-loop watchdog. It records total samples, maximum scheduling lag, count of wakeups delayed by at least one second, the last slow wakeup, and the coarse control-loop phase active during that delay. The operational heartbeat and Issue #469 render these values alongside record-pump, checkpoint, and per-lane websocket health.

This is diagnostic-only. It changes no market-data freshness threshold, strategy rule, risk limit, sizing rule, execution behavior, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### Index opening-opportunity mark paths by market — 2026-10-02

The continuous-paper context refresh records forward marks for opening opportunities. The path store previously implemented each market observation by calling `iter_paths()`, which globbed, read, JSON-decoded, validated, and sorted every historical path file. Because context refresh calls this once per market, runtime cost grew with both market count and total accumulated evidence and could block the asyncio event loop as the ledger expanded.

The store now validates persisted path files once when it opens, maintains an in-memory mirror keyed by opportunity id, and maintains a second index containing only incomplete paths by market. Registering and appending a mark update both the durable file and the indexes. `observe()` now touches only incomplete paths for the observed market, while `iter_paths()`, record counts, completion counts, and state digests use the validated in-memory mirror rather than rescanning disk.

Durable JSON files remain authoritative across process restarts: a new store rebuilds and validates both indexes from disk before use. Path semantics, completion horizons, mark ordering, source provenance, and terminal evidence are unchanged.

This is a performance/data-plane reliability change only. It changes no strategy threshold, risk rule, sizing rule, execution semantics, readiness gate, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### Race-safe event-loop stall phase attribution — 2026-10-02

The first watchdog-enabled worker measured genuine event-loop freezes above 80 seconds, but the reported phase could be changed by a different task immediately after the loop resumed and before the watchdog itself was scheduled. Phase attribution is now captured at the moment each watchdog sleep is scheduled, so a delayed wake reports the phase that was active before the stall. The heartbeat also preserves the phase observed after resumption for comparison.

The live control loop now labels context-path observation, exit-book capture, selected-context replay pumping, rank refresh, funding refresh, L2 recovery, selection refresh, heartbeat rendering, and checkpoint snapshot creation separately. This provides enough resolution to identify the synchronous section responsible for a future long stall.

This is diagnostic-only. It changes no market-data threshold, strategy logic, risk rule, sizing, execution behavior, readiness gate, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### Event-loop max-stall phase attribution — 2026-10-03

The active continuous-paper worker is currently producing healthy decision epochs, but repeated systemic L2 recovery remains excessive. Hyperliquid documents `l2Book` as a snapshot feed pushed on blocks, while the paper eligibility ceiling remains 5 seconds. Runtime telemetry has observed event-loop lag approaching that same ceiling, making it necessary to identify the exact blocking phase rather than relax book freshness or continue restarting otherwise healthy feeds.

The event-loop watchdog now preserves the exact wakeup that established the lifetime maximum lag, plus per-phase slow-wakeup counts and per-phase maximum lag. The operational heartbeat and Issue #469 render those diagnostics alongside the existing last-slow-wakeup, record-pump, checkpoint, and redundant-L2 health telemetry.

This change is diagnostic only. It does not alter market-data freshness limits, websocket subscriptions, L2 recovery behavior, strategy thresholds, risk vetoes, sizing, execution, readiness, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### Transient context-refresh fail-closed recovery and failed-run handoff — 2026-10-03

Continuous paper run `37096513901` terminated after Hyperliquid's mainnet `metaAndAssetCtxs` endpoint returned repeated HTTP 502 responses during the normal 30-second context refresh. The run had already preserved exact paper state, but the workflow's successor steps were conditioned on overall job success, so no successor was dispatched from that valid artifact.

Periodic context refresh now treats exhausted Hyperliquid 429/5xx/transport failures as transient data-plane failures. The runtime records refresh attempt/success/failure/consecutive-failure telemetry, preserves the prior context timestamp without pretending it is fresh, publishes the error, and retries on the next normal context poll. If the outage persists, the unchanged context-age gate naturally fails closed and prevents new exposure.

Continuous-paper state handoff also now accepts exact artifacts from completed paper runs whose conclusion is either success or failure. Fast-resume successor dispatch runs whenever the exact resume artifact uploaded successfully, even if the trader step failed. The durable fallback uses the same exact-run binding when fast resume dispatch is unavailable. Watchdog/manual recovery may likewise select a completed failed run only when its named durable artifact exists and passes the existing restore validation.

No context freshness limit, strategy threshold, risk rule, sizing rule, execution assumption, readiness gate, promotion state, or live-order authority is relaxed.

**LIVE TRADING: DISABLED.**


### LONG+trend carveout downstream shadow — 2026-10-03

Risk-rejected forward-markout evidence now shows that the frozen combined entry filter's pure `long_trend` block has positive mean directional returns across the observed 5m, 15m, and 60m horizons. That is not enough to remove the veto because the existing stack stops at the combined layer and therefore does not record whether the same opportunity would subsequently be blocked by two-strike or momentum.

The full-stack forward-markout research path now evaluates a parallel no-LONG-trend-veto challenger out of band. The live/frozen stack decision remains unchanged. For a pure `long_trend` block, the challenger preserves the top-10 rank requirement, applies the same two-strike state, then evaluates the same frozen momentum rule. Rank-above-10 blocks remain blocked. Existing non-combined opportunities inherit the original downstream decision.

Both risk-approved and risk-rejected summaries now carry challenger decision counts, block-layer counts, integrity misses, and the same fixed 5m / 15m / 60m markout review summaries. The new fields are descriptive only and have zero execution, promotion, readiness, sizing, or risk authority.

This creates the evidence needed to test whether removing only the blanket LONG+trend veto can improve opportunity selection without weakening the rest of the entry stack.

**LIVE TRADING: DISABLED.**


### LONG+trend carveout append-only fast-markout ledger — 2026-10-03

The no-blanket-LONG+trend-veto downstream shadow introduced in #801 now has a dedicated evidence family instead of relying on one worker's compact summary.

Issue #802 is the append-only status surface. Its ledger accepts only naturally acquired risk-rejected opportunities carrying the exact #801 carveout candidate identity. The original frozen stack decision and the challenger decision are both preserved. Pure LONG+trend combined blocks may continue through the unchanged two-strike and momentum layers; rank-above-10 blocks must remain blocked, and non-combined decisions must remain unchanged.

Only opportunities whose fixed 5m / 15m / 60m outcomes are terminal become immutable. Pending and missing-path outcomes remain unfrozen. Every prior terminal row must remain byte-for-byte equivalent after canonicalization, and each source is bound to its exact paper run, run attempt, compact artifact name, and SHA-256 digest.

The review gate can authorize only a deeper paper execution-shadow investigation. Every horizon requires at least 20 settled opportunities, 5 ADMIT, 5 BLOCK, 5 LONG, 5 SHORT, 4 markets, positive admitted mean, negative blocked mean, positive and leave-one robust ADMIT-minus-BLOCK separation, plus at least 10 reopened pure LONG+trend opportunities across 4 markets with positive leave-one-opportunity and leave-one-market robustness.

Passing this gate cannot alter the frozen entry stack, risk limits, sizing, candidate readiness, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### LONG+trend carveout observed stop-path survival — 2026-10-03

The durable LONG+trend carveout fast-markout ledger can show a positive 5m / 15m / 60m directional return even when the original decision-time stop would have been crossed earlier. Fixed-horizon recovery therefore is not, by itself, evidence that reopening the pure LONG+trend cohort would produce a viable paper trade.

The full-stack forward-path source now records a research-only stop-path overlay for every opportunity. It binds the exact decision-time invalidation price and entry reference to the already persisted opening-opportunity mark path. For each fixed horizon it reports only what the captured causal marks can prove: an observed stop crossing, an observed-path survivor, or an explicit unresolved state when stop/path/markout evidence is insufficient. It never infers unobserved intramillisecond prices.

The append-only LONG+trend carveout ledger preserves the new stop-path lineage on terminal rows and derives per-horizon reopened-cohort stop-evaluable count, observed crossings, observed survivors, crossing fraction, and median time-to-stop. Existing pre-overlay ledger rows and summaries remain valid, while the workflow waits for a stop-aware compact source before crediting new evidence.

This stop-path overlay is descriptive only and is deliberately excluded from the existing execution-shadow investigation readiness gate. It does not simulate stop fills, slippage, position sizing, funding, replacement capacity, or a complete counterfactual lifecycle. It changes no strategy threshold, risk veto, sizing rule, execution behavior, readiness gate, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### Risk-rejected observed stop-path overlay ledger — 2026-10-03

Issue #774 already contains immutable fixed-horizon markout evidence for risk-rejected opportunities. Those rows cannot be retroactively enriched with newly introduced stop-path fields without violating the append-only contract. A separate Issue #805 evidence family now preserves observed stop-path outcomes keyed to the same opportunity IDs.

The overlay accepts only risk-rejected full-stack opportunities from stop-aware compact paper sources. It binds the exact source paper run, attempt, artifact name, and digest; preserves stack decision, block layer, combined-filter reason, and hard-risk reasons; and freezes a row only after every fixed stop-path horizon is resolved. Missing or still-pending paths remain unfrozen.

At 5m / 15m / 60m the ledger reports observed stop crossings, observed-path survivors, crossing fraction, median time-to-stop, and market breadth. The same metrics are broken down by frozen stack block layer and combined-filter subreason so later price recoveries can be distinguished from setups that actually survived their original stop.

The claim is deliberately narrow: a survivor means no captured causal mark crossed the original decision-time stop before that horizon. It does not infer the unseen intrablock path and does not simulate stop fill price, slippage, funding, sizing, portfolio capacity, or a complete counterfactual trade lifecycle.

This overlay changes no strategy threshold, risk veto, risk limit, sizing rule, execution behavior, candidate readiness, promotion state, or live-order authority. Existing Issue #774 rows remain untouched.

**LIVE TRADING: DISABLED.**


### Stop-gated LONG+trend carveout readiness — 2026-10-03

The LONG+trend carveout ledger already reported whether reopened opportunities crossed or survived the original decision-time stop, but that evidence was descriptive only: the execution-shadow investigation gate could still pass with no stop-path coverage.

The gate now requires the existing forward-return and robustness conditions plus complete observed stop-path coverage for the reopened LONG+trend sample at every fixed horizon. Among those evaluable reopened opportunities, observed path survivors must strictly outnumber observed stop crossings. This reuses the existing reopened sample floor of at least 10 opportunities across at least 4 markets instead of introducing a looser parallel sample.

Previously published ledger artifacts remain valid through an explicit pre-stop-readiness compatibility summary. Immutable rows are unchanged.

Passing this gate still authorizes only deeper paper execution-shadow investigation. It does not change the frozen entry stack, risk limits, sizing, execution, candidate readiness, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**

### Risk-budget stop-survival investigation gate — 2026-10-03

The risk-rejected return ledger already requires a diversified, robust positive forward-markout sample before any rejected reason can be considered for deeper risk-budget investigation. Return evidence alone is not enough to show that a blocked setup would have survived its original decision-time stop.

The append-only risk-rejected stop-path ledger now adds a separate, necessary stop-survival gate over only the frozen full-stack ADMIT rows that were rejected by risk. For each risk reason and each fixed 5m / 15m / 60m horizon it requires complete observed stop-path coverage, at least 12 evaluable opportunities across at least 4 markets with at least 3 LONG and 3 SHORT, strictly more observed path survivors than observed stop crossings, and a positive survivor-minus-crossing margin after removing any one opportunity and after removing any one market.

The gate is deliberately conjunctive with the existing return/economic gate in Issue #774. Passing the stop-survival gate alone cannot relax a risk limit, and passing the return gate alone cannot relax a risk limit. Both remain research evidence for a later, explicit investigation only.

Previously published stop-path ledger artifacts remain valid through explicit legacy-summary compatibility. Immutable rows and their source binding are unchanged.

This changes no risk limit, sizing rule, strategy threshold, execution behavior, candidate readiness, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**

### Conjunctive risk-budget investigation dossier — 2026-10-03

The risk-rejected return ledger and observed stop-path ledger now have independent research gates, but they can complete at different times and may temporarily point at different paper sources. A manual comparison could therefore combine evidence that is individually valid but not source-aligned.

A new research-only conjunctive dossier binds the latest durable return and stop ledgers by the exact authenticated paper run ID, run attempt, compact artifact name, artifact digest, and common stack start. It reports a risk reason as ready for deeper investigation only when both component ledgers use current gate formats, both cumulative integrity flags are clean, the source identities match exactly, and the same reason passes both the economic-return gate and the robust stop-survival gate.

If either ledger is missing, stale-format, source-misaligned, or integrity-dirty, the dossier fails closed and reports no conjunctively ready reason. Issue #809 is the dedicated status surface and a durable JSON dossier artifact is published on clean workflow runs.

Conjunctive readiness authorizes only deeper research investigation. It does not relax a risk veto, change a risk limit, alter sizing or execution, change strategy/candidate readiness, promote a strategy, or enable live orders.

**LIVE TRADING: DISABLED.**


### Lane-local reconnect for systemic L2 subscription silence — 2026-10-03

Live worker `37117105394` showed a repeated market-data failure pattern even after prior recovery and event-loop fixes: 21 guarded stale-L2 recoveries were promoted successfully, reseeding 420 books with zero REST failures, while healthy decision epochs could still later lose most deep readiness.

The per-lane diagnostics isolated the failure before recovery. Both redundant websocket lanes remained connected and continued receiving server traffic within roughly one second, but all 20 L2 subscriptions on each lane were stale and had lost readiness at the same time. The last observed L2 exchange-vs-receive skew remained sub-second, and event-loop stalls were well below the 15-second L2 freshness ceiling. Hyperliquid documents `l2Book` as a snapshot feed pushed on blocks and allows up to 1000 websocket subscriptions, so this pattern is treated as channel-level subscription silence rather than normal quiet-market behavior or quota exhaustion.

`WebSocketSupervisor` now has an opt-in systemic-L2 stale reconnect policy. Continuous paper enables it at the same 50% majority threshold used by the outer systemic recovery logic. When at least that fraction of a lane's L2 subscriptions are stale while the websocket itself is still receiving recent server messages, only that lane reconnects and resubscribes. The existing redundant-lane supervisor, REST reseed, and whole-group replacement remain unchanged as fail-closed fallback paths.

A dedicated `systemic_l2_stale_reconnect_count` is exposed per lane so Issue #469 can verify whether lane-local healing reduces expensive whole-group recovery churn.

No L2 freshness threshold, eligibility rule, strategy threshold, risk veto, sizing rule, stop, readiness gate, promotion state, or live-order authority is relaxed.

**LIVE TRADING: DISABLED.**


### Reset L2 freshness on reconnect before outer escalation — 2026-10-03

Worker `37120841453` on `bd6ee2c` exposed a recovery coordination loop: lane-level systemic-L2 reconnects were followed by repeated full-group recoveries and REST reseeds. The pre-recovery telemetry showed both lanes reconnecting while the outer group simultaneously treated their temporarily cleared readiness sets as systemically unhealthy.

The websocket supervisor now resets only its L2 freshness anchors at the start of each new socket session. Old exchange timestamps cannot immediately poison a fresh reconnect; each L2 subscription gets one existing freshness window to deliver a real snapshot. Readiness remains revoked until genuine fresh L2 data arrives, so the runtime still fails closed for trading.

The outer supervisor-group health check now escalates only when the same markets are actually stale across every redundant lane. Temporary missing readiness during reconnect no longer causes an immediate full-group rebuild; replacement-group startup still requires every selected market to become ready, and decision-time missing/stale deep data remains ineligible.

No freshness ceiling, eligibility threshold, strategy rule, risk limit, sizing rule, stop, promotion state, or live-order authority is relaxed.

**LIVE TRADING: DISABLED.**

### Post-integrity risk evidence cohort — 2026-10-03

The risk-rejected return and observed-stop ledgers preserve cumulative source-integrity failures forever, which is correct for auditability but previously meant one historical missing/stale rank or momentum-lineage miss could permanently block every later risk-budget investigation even after the capture path was repaired.

The full-stack forward-markout source now records the exact latest timestamp of any risk-rejected integrity miss covered by its existing integrity definition. Both risk-rejected ledgers preserve their cumulative integrity flag and immutable historical rows, while also deriving a separate post-integrity cohort that begins strictly after that latest miss. Legacy dirty sources without an authenticated miss boundary remain ineligible for the clean cohort.

The post-integrity return cohort must satisfy the same precommitted risk-investigation economics gate from scratch. The post-integrity stop cohort must satisfy the same independent observed-stop-survival gate from scratch. The conjunctive dossier can use the clean suffix only when both ledgers come from the same authenticated source and agree on the exact same cohort start. Otherwise it remains blocked by source integrity.

This does not erase old evidence, reinterpret a dirty source as clean, relax the weekly drawdown lockout, change entry filters, sizing, execution, promotion state, or live authority.

**LIVE TRADING: DISABLED.**


### WebSocket supervisor scheduler fairness — 2026-10-03

Lane-level runtime telemetry showed repeated systemic L2 churn with both redundant lanes simultaneously stale/disconnected: 53+ successful replacement promotions and more than 1,000 fresh REST reseeds still returned to 16 stale books and zero deep-ready markets. The same worker reported event-loop wakeup lag up to 5.3 seconds while individual record-pump processing remained below 300ms with zero lock wait.

Hyperliquid documents the mainnet `l2Book` websocket as a snapshot feed pushed on each block (subject to the feed's 0.5-second push floor), so a 20-market cohort freezing together is not normal quiet-market behavior. The supervisor could consume already-buffered websocket messages through immediately completing awaits without an explicit scheduler handoff, allowing one hot task to monopolize the event loop across a burst.

The websocket supervisor now yields to the asyncio scheduler after every received server message. This preserves every event, ordering, deduplication, exchange-time freshness, gap semantics, subscriptions, risk rules, execution rules, and the existing 15-second book freshness ceiling. A regression test proves another ready task can run between buffered websocket messages.

No market-data threshold, strategy rule, risk budget, sizing rule, stop, readiness gate, promotion state, or live-order authority changes.

**LIVE TRADING: DISABLED.**


### Stagger redundant L2 lane reconnects — 2026-10-03

Worker `37127438608` on `e755c4c` still showed 16 stale books and zero deep-ready markets after 18 successful full-group recoveries. Pre-recovery lane telemetry showed both redundant websocket lanes disconnecting together after the same systemic-L2-stale trigger, while post-recovery telemetry showed both lanes immediately healthy with 20/20 ready markets and sub-second L2 ages.

The redundant lanes now keep the existing 15-second L2 freshness ceiling but no longer self-reconnect at the same instant. Lane 0 retains the existing systemic-stale reconnect timing; lane 1 receives a fixed 5-second reconnect grace. This preserves strict decision-time stale-book rejection while giving one lane time to reconnect and resubscribe before the second lane tears down.

Server-silence recovery, outer REST reseeding, full-group replacement recovery, stale-data fail-closed behavior, strategy thresholds, risk limits, sizing, stops, readiness, promotion, and live-order authority are unchanged.

**LIVE TRADING: DISABLED.**


### Separate L2 subscription liveness from book freshness — 2026-10-03

The staggered-lane successor showed that synchronized teardown was reduced: before its first full-group recovery, lane 0 was disconnected/reconnecting while lane 1 remained connected. However, lane 1 was still classified as stale even while server traffic continued, revealing that the supervisor's systemic reconnect watchdog was using L2 exchange timestamps as a proxy for subscription liveness.

The websocket supervisor now maintains two distinct clocks. Exchange-time age continues to drive strict stale-book gaps and decision eligibility. Receive-time message age drives only the systemic-subscription reconnect watchdog. Exact duplicate L2 snapshots are still deduplicated before replay processing, but their arrival now refreshes receive-time liveness because they prove the subscription delivered a message.

This prevents a live L2 subscription from being torn down merely because its book exchange timestamp has not advanced. It does not make an old book eligible, does not close a stale-book gap, and does not change the existing 15-second freshness ceiling, REST recovery, strategy, risk, sizing, stops, readiness, promotion, or live-order authority.

**LIVE TRADING: DISABLED.**


### Reopened LONG+trend fixed-horizon exit timing — 2026-10-03

The risk-rejected carveout now has enough structure to separate entry quality from hold duration. Pure LONG+trend setups reopened by the no-veto challenger already report fixed 5m, 15m, and 60m forward returns plus observed original-stop survival, but the ledger did not directly compare those horizons opportunity by opportunity.

The append-only carveout ledger now derives a fixed-horizon exit-timing view for reopened pure LONG+trend setups with all three horizons settled. It reports which horizon is best per opportunity, how often either 5m/15m beats 60m, and leave-one-opportunity / leave-one-market robustness for 5m-minus-60m, 15m-minus-60m, and 5m-minus-15m return differences.

This is descriptive timing evidence only. It does not change the existing carveout investigation gate, entry rules, exits, stops, risk limits, sizing, candidate readiness, promotion state, or live-order authority. Previously published ledger summaries remain valid.

**LIVE TRADING: DISABLED.**


### Reconnect lanes on stale L2 payload timestamps — 2026-10-03

Worker `37129994357` on #818 still showed systemic decision-time L2 staleness after repeated successful REST reseeds and supervisor replacements. Pre-recovery telemetry showed a lane receiving recent server traffic while all 20 L2 streams remained stale, and post-recovery lanes immediately returned to sub-second exchange-time freshness.

The current official Hyperliquid WebSocket contract describes `WsBook` as a snapshot feed pushed on each block (at least 0.5 seconds since the previous push). Therefore a lane that continues receiving server traffic or exact duplicate messages while most L2 exchange timestamps stop advancing beyond the existing freshness window is not considered healthy enough to suppress reconnect.

The supervisor now reconnects when either the majority of L2 subscriptions become receive-time silent or the majority of their exchange timestamps remain stale beyond the existing reconnect threshold while the websocket itself is active. Duplicate arrivals still refresh socket/subscription receive-time liveness and remain deduplicated from replay, but they cannot mask frozen L2 payload timestamps.

No book-freshness ceiling, eligibility rule, strategy threshold, risk limit, sizing rule, stop, readiness gate, promotion state, or live-order authority is changed.

**LIVE TRADING: DISABLED.**


### Stagger-aware L2 group recovery escalation — 2026-10-03

Worker `37132034182` on `105c412` showed the lane-level reconnect watchdog working, but also exposed an escalation race. Lane 0 had already entered its frozen-L2 reconnect path while lane 1 was still inside the configured redundant-lane reconnect stagger. During that overlap both lanes could briefly report the same markets stale, causing the control loop to escalate immediately to REST reseed plus whole-group websocket replacement.

The runtime now distinguishes hard book freshness from full-group recovery escalation. Books still become stale at the existing eligibility ceiling and remain ineligible for trading immediately. However, whole-group recovery now waits for each redundant lane to exceed its lane-specific recovery grace, giving the staggered lane reconnect mechanism time to heal the feed before the runtime tears down both lanes.

The default escalation window is derived from the existing reconnect stagger: with the current 5-second stagger, lane 0 receives 5 seconds of self-recovery headroom after the hard freshness ceiling and lane 1 receives 10 seconds. If the redundant lanes remain stale beyond those windows, the existing REST reseed and replacement-group fallback still executes fail-closed.

No book freshness threshold, strategy threshold, risk rule, sizing rule, stop, readiness gate, promotion state, or live-order authority is relaxed.

**LIVE TRADING: DISABLED.**


### Proactive L2 failover freshness headroom — 2026-10-03

Worker `37134013144` confirmed that stagger-aware group recovery stopped whole-group churn while one redundant websocket lane remained healthy. However, its first decision epoch still saw seven `stale_book` rejections even though the healthy lane was fresh across all 20 markets. Hyperliquid documents `l2Book` as a snapshot feed pushed on each block subject to a minimum 0.5-second push interval, so a healthy lane should provide ample headroom before the existing 5-second eligibility ceiling.

The websocket supervisor now uses an explicit failover headroom before the hard paper-trading freshness limit. With the current defaults, a lane is declared stale for failover purposes at 4 seconds while strategy eligibility continues to reject books only at 5 seconds. This gives the redundant mux one second to switch to the healthy lane and drain fresh standby snapshots before the decision pipeline reaches the trading stale threshold.

The headroom is versioned as `websocket_l2_failover_headroom_ms=1000` in the continuous-paper configuration and workflow. It must be non-negative and smaller than the hard book-age ceiling.

This changes only failover timing. The 5-second book freshness eligibility rule, 1-second execution-book limit, strategy logic, risk vetoes, sizing, stops, readiness, promotion state, and live-order authority remain unchanged.

**LIVE TRADING: DISABLED.**


### Compact LONG+trend execution-shadow source — 2026-10-03

The LONG+trend carveout evidence gate now has a defined next research stage, but the generic compact paper artifact does not carry the raw opening-opportunity risk request, exact decision-time L2 book, and forward path needed for a deeper paper execution shadow. The full resume artifact is materially larger and is not an appropriate research dependency.

Continuous paper now emits a candidate-specific compact source containing only risk-rejected pure LONG+trend opportunities that the frozen carveout would reopen, and only when the baseline risk reason is exactly `weekly_drawdown_lockout`. Each exported row binds the original opening-opportunity evidence, captured decision-time book/risk request, carveout lineage, and its forward path when available. Missing opportunity lineage fails closed; missing paths remain explicit rather than fabricated.

The source explicitly requires the durable LONG+trend fast-markout gate before any execution-shadow interpretation. Exporting this evidence does not start a shadow, alter the live/frozen entry stack, relax weekly drawdown protection, change sizing/planning/execution, modify readiness, or authorize live orders.

The compact learning artifact now includes `prospective-long-trend-execution-shadow-source.json`, and changes to the source exporter participate in continuous-paper runtime handoff detection.

**LIVE TRADING: DISABLED.**


### LONG+trend captured execution shadow — 2026-10-03

The no-LONG-trend-veto challenger has accumulated a small but directionally interesting reopened sample, while the real paper account remains protected by the weekly drawdown lockout. Commit #825 added a compact source that exports only pure LONG+trend opportunities rejected exclusively by `weekly_drawdown_lockout` and reopened by the frozen challenger, together with their exact captured risk request, decision-time L2 book, execution instrument, and forward mark path.

A dedicated research-only execution shadow now consumes that authenticated source. It neutralizes only the weekly drawdown veto in an isolated copy of the captured request by resetting the copied rolling peak to current equity, then re-runs the unchanged independent risk engine. Any other risk veto remains binding. Risk-approved counterfactuals continue through the existing opening planner and visible-book IOC simulator using the captured instrument, book, latency, fee, slippage, notional, liquidity, and risk ceilings.

Filled shadows report entry-fee-adjusted 5m / 15m / 60m mark-to-market PnL, directional returns, sign counts, profit factor where defined, and leave-one-opportunity / leave-one-market PnL robustness. Replacement exits, exit fees, funding, and complete realized trade lifecycle PnL are intentionally not modeled at this stage.

Issue #828 is the dedicated continuously refreshed status surface. Its workflow binds the exact completed paper run, run attempt, compact artifact identity, artifact digest, and source SHA before evaluation.

This path has no authority to relax weekly drawdown protection, change the live/frozen entry stack, alter sizing or execution, change readiness, promote a candidate, or enable live trading.

**LIVE TRADING: DISABLED.**


### LONG+trend execution-shadow config lineage — 2026-10-03

The captured execution shadow now binds each new source artifact to the exact `PaperExecutionConfig` used by the paper worker. Source schema v2 records the execution config version, latency, book/context freshness ceilings, funding grace, IOC slippage ceiling, taker fee rate and fee schedule, native minimum notional, and paper leverage ceiling together with a dedicated config digest covered again by the source digest.

The evaluator treats v2's captured config as authoritative for risk/planner/visible-book IOC replay. Legacy v1 sources remain temporarily evaluable only with an explicit `phase7-v1` fallback so the first #825 artifact can be studied instead of discarded. Every summary states whether its config came from the captured v2 source or the legacy evaluator fallback, and reports the exact config digest.

This prevents future execution-model changes from being silently mixed into the same counterfactual evidence. The change is provenance-only: it does not alter the paper trader's execution config, risk limits, strategy, sizing, stops, readiness, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**

### Live clean-breakeven shadow preview — 2026-10-04

The profit-lock execution shadow remains the strongest mature exit challenger in current evidence: the durable `breakeven_after_0_5r` shadow is review-ready on its touched predecessor sample with a positive, leave-one-trade and leave-one-market robust PnL/R delta. The separate clean prospective gate remains correctly blocked by insufficient future sample and therefore still has no execution or promotion authority.

The continuous-paper operational heartbeat now exposes a deliberately small preview of that clean prospective candidate for currently open positions. It reports only candidate identity/start, clean open-position counts, activation/trigger counts, and per-position activation/trigger state plus the breakeven candidate stop once activated. It reads only current open rule state and does not serialize historical shadow outcomes into the hot heartbeat path.

This is observability only. It does not move the actual paper stop, alter strategy/risk/sizing/execution, lower the clean prospective evidence gate, grant candidate readiness, promote a strategy, or enable live orders.

**LIVE TRADING: DISABLED.**

### Lazy equity-state restart dedup — 2026-10-04

Continuous-paper replay construction no longer preloads every historical evaluation equity account-state ID at restart. The prior indexed-column optimization removed payload decoding but still left startup cost proportional to the full accumulated equity-fact history.

The replay pipeline now starts with an empty session-local dedup set. When an account state is first observed in the resumed session, the evaluation store performs a covered indexed lookup on the existing unique `(replay_run_id, account_state_id)` identity; historical states are reused and new states are recorded exactly as before. Regression coverage forbids both full equity payload iteration and account-state-ID iteration during pipeline construction while preserving the existing restart-idempotency contract.

This changes restart performance only. Evaluation fact identity, strategy, risk, sizing, stops, paper execution, readiness, promotion state, and live-order authority are unchanged.

**LIVE TRADING: DISABLED.**



### Recurring loss-context economic stability gate — 2026-10-07

The loss-streak audit now converts recurring bad-entry patterns into context-specific counterfactual filter candidates instead of treating aggregate LONG/SHORT performance as a strategy rule.

Candidate contexts must include `lead_strategy` and entry-time market state; direction-only candidates are explicitly forbidden. Discovery uses the earlier chronological cohort, while validation uses later trades. A candidate is stable only when blocking matching trades would improve realized net PnL after costs on the holdout, across at least three markets, with positive leave-one-trade and leave-one-market robustness and positive economics in both later chronological blocks.

This is research-only and descriptive. It does not block trades, change the active strategy, weaken risk, alter sizing, promote a candidate, or enable live orders. A stable loss context still requires a separate prospective freeze before any future strategy use.

**LIVE TRADING: DISABLED.**


### Ignore stale queued paper successors across upgrades — 2026-10-07

A live upgrade exposed a handoff deadlock: an older workflow-dispatch successor could remain queued behind its predecessor's concurrency group, then be mistaken by a newer exact successor as an active trader even though it had never reached the trader step. This could leave the newest successor skipping while the stale queued run later resumed from older state.

The continuous-paper guard now ignores only queued/pending runs that are both older than the current run and pinned to an older head SHA. Same-head queued runs, newer queued runs, and any run whose trader step is queued/pending/in-progress still block as before. Once a newest-head successor starts trading, any stale older queued run that later materializes will see that active trader and skip.

Continuity/safety only. No strategy, risk limit, sizing, stop, promotion, or live-order behavior changes.

**LIVE TRADING: DISABLED.**


### Frozen recurring loss-context prospective shadow — 2026-10-07

The D-037 loss-context stability gate now has its missing clean-future stage. When the audit finds a stable context, Cocomelon deterministically chooses the simplest robust context, freezes it once, preserves the exact source run/head lineage, waits six hours, and then scores only later realized paper trades that match the frozen entry-time context.

The future score is economically symmetric: blocking a later loser improves filter delta, while blocking a later winner reduces it. A candidate cannot become review-ready unless the future sample is complete, diversified across markets, leave-one-trade and leave-one-market robust, and positive across three later time blocks.

This still does not change the active paper strategy. It creates a clean prospective answer to a narrower question: whether one exact repeated bad setup remains worth avoiding after we stop looking at the evidence that discovered it.

**LIVE TRADING: DISABLED.**


### Durable paper evidence continuity — 2026-10-07

The evidence graph now distinguishes a failed paper trader from a valid paper session whose GitHub workflow turned red later in the handoff/research tail. Consumers accept the latter only under a strict authenticated contract: successful trader, successful durable-state measurement/publication, successful required source-artifact publication, exact run/attempt/repository lineage, and successful fast-successor dispatch whenever the redundant fallback successor failed.

This fixes the observed case where valid compact, timing, cadence, feature, and durable-state artifacts were being ignored because the redundant fallback receipt failed after the real successor had already been queued. Arbitrary failures remain fail-closed.

Control-plane/evidence continuity only. No strategy, risk, sizing, stop, promotion, or live-order behavior changes.

**LIVE TRADING: DISABLED.**


### Loss-context research cadence hardened — 2026-10-07

The recurring-loss context audit no longer waits for a code-upgrade exit. It rebuilds after either normal paper duration completion or an upgrade-requested handoff, but only after the successor has already been dispatched. Unknown exits remain rejected.

That means Cocomelon can keep accumulating context-specific bad-entry evidence during ordinary operation instead of learning only when the repo changes. The D-038 prospective freeze and all authority-negative safeguards are unchanged.

**LIVE TRADING: DISABLED.**


### Loss-context fixed-schedule account gate — 2026-10-07

The recurring loss-context path now distinguishes “avoids losses” from “leaves a profitable portfolio.” After D-038 prospective scoring, a downstream paper-research gate evaluates the full resolved post-embargo cohort with matching bad-context trades removed and all non-matching realized trades unchanged.

The filtered fixed-schedule portfolio must itself have positive net PnL and net-R while also improving on baseline. Both the filtered portfolio and its improvement must survive leave-one-trade and leave-one-market checks. The avoided-loss PnL must exactly reconcile to D-038, and unresolved future lineage keeps the gate closed.

A pass does not activate the filter. It only permits the next research question: whether freed capacity and replacement opportunities preserve the benefit. Capacity reflow and recursive replacements remain unmodeled here and are required before any later strategy use.

No LONG or SHORT side is suppressed globally. Strategy, risk, sizing, stops, promotion, and execution remain unchanged.

**LIVE TRADING: DISABLED.**


### Loss-context capacity-reflow causality — 2026-10-07

The D-041 account gate now has a downstream reflow investigation. It stays disabled until the frozen loss-context candidate is prospectively review-ready and the filtered fixed-schedule portfolio is profitable and robust.

When enabled, it examines later opportunities rejected for aggregate-risk or correlation-bucket capacity and reruns the normal capacity math with one captured active position removed. The release is credited to the loss-context candidate only when that exact holder was opened after the prospective boundary and its entry context matches the immutable frozen bad setup. A replacement opportunity that itself matches the same bad setup is excluded.

The output is still only capacity-release sensitivity. Replacement entry fills, exits, realized PnL, and recursive portfolio effects are not claimed yet. The next frontier is to replay those causally unblocked opportunities through the captured execution path.

**LIVE TRADING: DISABLED.**


### Loss-context exact holder-release execution — 2026-10-07

The loss-context reflow path now has an execution gate after causal capacity attribution. For every D-042 release option, Cocomelon looks for the matching captured holder-release book and replays the existing reduce-only paper execution path with the bound execution configuration.

Only exact full closes are exposed to the next replacement-entry research stage. Missing capture, legacy/unbound execution configuration, planning rejection, partial fill, or no fill stays visible and cannot be counted as freed capacity.

The output explicitly separates causal release options, captured books, missing records, exact-config records, full/partial/no fills, terminal contribution, and the subset ready for replacement-entry investigation.

Research only; no strategy, risk, sizing, stop, position, promotion, or live-order change.

**LIVE TRADING: DISABLED.**
