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
