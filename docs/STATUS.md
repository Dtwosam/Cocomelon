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

