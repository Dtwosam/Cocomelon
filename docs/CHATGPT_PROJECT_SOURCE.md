# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing Cocomelon across ChatGPT chats. Live GitHub state and authoritative repository docs always outrank this summary.

**Snapshot updated:** 2026-09-26  
**Repository:** `Dtwosam/Cocomelon`  
**Current verified `main` at snapshot:** `f34dd1de5fd2e73151d0ebb6e73b7b37355043dd`  
**Latest verified development CI:** `35614793455` on PR #237 implementation head — success  
**Venue:** Hyperliquid perpetual futures  
**Observation:** genuine public Hyperliquid mainnet  
**Execution:** paper/shadow only  
**Hyperliquid testnet:** forbidden  
**Live trading:** **DISABLED**  
**Phase 10:** **OFFLINE LEARNING ENGINEERING ACTIVE; PROMOTION/LIVE BLOCKED**

---

## 0. Current paper-trade interpretation — read this before answering current-trade questions

**Point-in-time verification:** 2026-09-26 00:57 UTC. This subsection is a bootstrap snapshot, not a substitute for re-checking live GitHub Actions and authenticated artifacts when a user asks "now", "today", or "current".

There are multiple paper-evidence families in this repository and they must not be conflated:

1. **Retired/touched V4 corpus** — historical development evidence. The trusted evidence dashboard showed 121 closed paper trades across 21 closed-trade days. V4 is retired/touched and demonstrated no edge. These trades are not evidence that the newly started campaign has already traded.
2. **Touched research replay lanes** — `scheduled-research-root`, `research-r1-exit-15m-v1`, and `research-r2-short-trend-quality-v1`. At the 2026-09-26 00:37 UTC research-dashboard snapshot, root had 14 closed trades (9 LONG / 5 SHORT), r1 had 6, and r2 had 1. These are separate from the clean prospective HYPE campaign.
3. **Active clean prospective HYPE V3 campaign** — candidate `hype-down-bearish-near-basket-long-4h-v3`, frozen under D-029. V3 began 2026-09-26 00:00:00 UTC, uses HYPE 1h anchors, a frozen LONG hypothesis, and an exact 4h prospective outcome horizon. Its first expected V3 anchor is 2026-09-26 00:59:59.999 UTC, with the pre-created capture run intended around 01:03 UTC.
4. **Learned-candidate clean/shadow evidence** — a later, separately authenticated path. Do not treat learned-candidate lifecycle/workflow state as the same thing as V3 prospective HYPE trading.

At the point-in-time check above, V3 transport/capture runs existed and were active, but the checked runs were still in transport/hold steps and had no authenticated V3 economic artifact yet. That statement can become stale quickly, so **always re-check the latest V3 run jobs and artifacts before repeating it**.

### Required interpretation rule for new chats

For any question about the "current paper trade":

- first inspect latest Actions activity for `Prospective HYPE V3`, scheduled research replay, and any learned clean/shadow follower that could own the newest economic evidence;
- inspect the relevant run's jobs/steps and artifact list;
- use authenticated evidence/state before saying a new trade opened, closed, or has PnL;
- never use Issue #82 alone for current trades — it primarily summarizes retired/touched V4 evidence;
- never use Issue #124 alone for current trades — it summarizes touched research lanes and can lag a separate prospective HYPE campaign;
- treat V3 transport receipts, heartbeat receipts, queue state, and workflow existence as **non-economic**;
- if a campaign is active but no authenticated trade row is visible, say exactly that: **campaign active; new economic trade not yet confirmed from authenticated evidence**;
- if authenticated trade evidence exists, report its candidate/market, direction, anchor/open time, settlement status, modeled or realized return type, and provenance lane.

Do not say "there are no paper trades" when what is actually known is only "this particular active campaign has not yet published a confirmed economic trade." Preserve the distinction between cumulative historical trades and the newest campaign.

---

## 1. Authority and continuation rule

Use this order:

1. current explicit user instruction;
2. `AGENTS.md`;
3. `docs/MASTER_SPEC.md`;
4. `docs/DECISIONS.md`;
5. `docs/BUILD_ORDER.md`;
6. active plan/spec under `docs/superpowers/`;
7. `docs/STATUS.md`;
8. this portable bootstrap.

Always inspect live `main`, recent Actions runs, open PR/review state, active V4 jobs, and trusted dashboard state before acting. Do not rebuild already-merged work. Use RED -> GREEN TDD for behavior changes and verify exact-head, PR-context, and post-merge CI before claiming integration is green.

The user expects autonomous engineering. Real-money activation is the permanent exception: no live exchange order placement until objective promotion gates pass and the user explicitly authorizes live mode/capital.

---

## 2. Locked safety boundaries

- Hyperliquid testnet is forbidden.
- Runtime observations are public Hyperliquid mainnet only.
- Current/default execution is paper/shadow.
- No wallet/private-key signing, transfer, withdrawal, or private-account execution belongs in research/evidence workflows.
- Strategy cannot bypass independent risk.
- No averaging down, martingale/loss-recovery sizing, or stopless positions.
- `NO_TRADE` is first-class.
- Historical L2/order flow may not be fabricated from candles.
- Research is **TOUCHED / NON-PROMOTIONAL** and cannot directly advance Phase 10 or enable live orders.

---

## 3. Retired V4 baseline

The formerly frozen `v4-baseline-4h-thesis-expiry` was explicitly revealed and retired under D-024.

The 100-trade / 18-day development snapshot was negative:

- gross PnL about `-537.62`;
- net PnL about `-629.91`;
- mean net R about `-0.298`;
- profit factor about `0.44`;
- realized closed-trade maximum drawdown about `7.80%`.

This evidence is permanently **TOUCHED / DEVELOPMENT-ONLY** and cannot become untouched OOS evidence.

Future scheduled V4 acquisition and automatic V4 one-shot evaluation for the retired baseline are disabled. The one acquisition that had already started before retirement, run `35524316366`, finished successfully and naturally without cancellation, retry, extension, backfill, or outcome conditioning. Authority sync/curation accepted its actual interval into the retired touched corpus.

Latest trusted dashboard snapshot recorded:

- 69 accepted V4 cohorts;
- 121 closed paper trades;
- 21 closed-trade days;
- 7,250 strategy decisions;
- economic edge: **RETIRED / TOUCHED — NO EDGE DEMONSTRATED**;
- live orders: **DISABLED**.

Later V4 cohorts are historical/touched only and may not be used to retune the locked r2 thresholds.

---

## 4. Active research frontier — historical two-sided learning

Primary plan: `docs/superpowers/plans/2026-09-21-historical-directional-learning.md`.

D-025 changes the primary architecture from a hand-filtered short-only challenger to a historical, direction-neutral learner.

Target behavior:

- study trustworthy historical market states across the dynamically eligible coin universe;
- reconstruct only features that were known at each historical timestamp;
- label future LONG and SHORT outcomes at predeclared horizons;
- learn side-specific expected net opportunity;
- choose LONG, SHORT, or NO_TRADE from evidence;
- keep eligibility and the independent risk engine as hard veto authorities;
- use chronological train/validation/test partitions plus embargo/walk-forward validation;
- never fabricate missing historical microstructure or leak future information into features.

Phase 9 satisfied its exit condition by honestly demonstrating that the retired V4 baseline did not show edge. **Phase 10 offline learning engineering is active.** Live trading and promotion remain blocked.

Current implementation frontier:

- deterministic bounded candle request windows respect the 5,000-candle ceiling;
- exact-timestamp outcomes record both LONG and SHORT gross returns and omit missing exact targets;
- resumable public-mainnet candle/funding backfill persists raw page envelopes and normalized records;
- source manifests preserve deterministic checksums, request/observed coverage, and gaps;
- funding page boundaries intentionally overlap for authenticated deduplication; conflicting duplicates fail closed;
- `cocomelon-historical-backfill` orchestrates multiple canonical markets/intervals through the existing rate-budgeted `InfoClient`;
- deterministic combined coverage reports preserve source/market/interval provenance;
- no model family or decision threshold is selected yet.

PR #235 implementation head `0b463d515b2f0914a1ff7aae5ddc8682a12b931d` passed CI run `35609936635` with compile, Ruff, strict mypy, full pytest, and research smoke.

PR #236 implementation head `4c04600d5835197209c5405c9a05d992db38f78a` passed CI run `35613448712` with compile, Ruff, strict mypy, full pytest, and real PyArrow historical-dataset export. The historical pipeline now reconstructs point-in-time candle/funding features, distinguishes exchange-time availability from later retrieval, refuses to bridge gaps, preserves explicit unavailable-feature state, authenticates source checksums/manifests, joins exact multi-horizon LONG/SHORT outcomes, and exports versioned Parquet training corpora through `cocomelon-historical-dataset`.

PR #237 implementation head `2e61ea9966e02475059e54b9c670d681ae4ae449` passed CI run `35614793455` with compile, Ruff, strict mypy, full pytest, and research smoke. The first learner is a transparent direction-neutral conditional baseline with shared cross-coin states, sample-gated coin calibration, separate LONG/SHORT estimates, chronological embargo/walk-forward folds, explicit fee/slippage plus conservative funding reserve, validation-only NO_TRADE calibration, and shared-versus-coin test reporting. A regression proves future test outcomes cannot alter the selected threshold.

### Preserved r2 experiment

`research-r2-short-trend-quality-v1` remains immutable and auditable as a secondary touched short-side hypothesis:

- parent: `scheduled-research-root`;
- strategy revision: `2ce088d69df01f044b0650b811b51015a5edda51`;
- execution max position age: 20 minutes;
- frozen r2-only rule: trend-led SHORT, baseline score 72–81 inclusive;
- trusted state: draft, 0 authenticated checkpoints, 0 closed trades.

The failed r2 attempt from natural campaign `35551385941` remains failed / NOT COUNTED and is never retried or backfilled. PR #228 fixed the shared replay-identity defect for future research, but r2 is no longer the product architecture or the sole gate to learning development.

Trusted research reference at the 2026-09-21 09:58 UTC snapshot:

- `scheduled-research-root`: 13 authenticated checkpoints, 10 closed trades, 7 closed-trade days, touched net PnL about `-37.2371`;
- legacy `research-r1-exit-15m-v1`: 7 checkpoints, 6 trades, 4 days, touched net PnL about `-36.9098`;
- r2: 0 authenticated checkpoints.

None of these results establishes verified edge.

---

## 5. Locked research and promotion gates

For registered touched economic candidates, D-023 fast-failure/promising rules remain intact.

For historical-learning candidates under D-025:

- historical backtests and training results are touched development evidence;
- feature rows may use only information available at the anchor timestamp;
- future observations appear only in explicit labels;
- train/validation/test order is chronological;
- test data cannot tune features, hyperparameters, costs, or decision thresholds;
- walk-forward evaluation is mandatory;
- LONG and SHORT are both available; NO_TRADE remains first-class;
- model output cannot weaken or bypass hard risk limits;
- a promising model must be frozen before any clean future validation begins;
- live promotion still requires all `MASTER_SPEC.md` gates, including >=500 closed mainnet paper trades, >=45 calendar days shadow, positive cost-complete untouched OOS/walk-forward evidence, acceptable drawdown/concentration, clean integrity, and explicit user authorization.

---

## 6. Current control-plane and paper-execution state

The authoritative V4 interval/completeness synchronization path remains in `.github/workflows/research-v4-registry-sync.yml`. Research admission depends on actual authoritative V4 coverage/disjointness, never nominal cron timing.

Recent frontier PRs:

- #205: added the deterministic r2 short-trend quality strategy seam;
- #206: registered and activated r2 as the research challenger default without economic dispatch;
- #207: retired future V4 acquisition/automatic one-shot evaluation for the disclosed failed baseline;
- #208: restored pre-publication and final rollout-verifier enforcement for root+r2;
- #209: made the trusted dashboard retirement-aware;
- #210: made r2 natural research the active execution plan;
- #211: fixed strategy-driven paper stop tightening so the updated stop is materialized atomically and survives restart;
- #212: refreshed the portable handoff to the current r2 frontier;
- #214: advanced the active r2 plan through the verified stop-durability fix;
- #215: fails paper restart reconciliation closed when the deterministic current immutable position event is missing or corrupted;
- #217: regression-locks LONG/SHORT tightened-stop persistence and fail-closed behavior on durable write failure;
- #219: rejects missing/unsupported paper execution store schema versions without rewriting them;
- #220: rejects missing/unsupported journal/replay store schema versions without rewriting them;
- #222: fails paper execution closed when durable order-plan persistence fails;
- #223: validates active-position opening-plan lineage on restart and runtime exit planning;
- #224: fails paper execution closed on funding-idempotency read errors before accounting mutation;
- #226: rejects structurally incomplete supported-version paper and journal/replay stores before migration DDL can silently recreate missing required tables;
- #228: scopes research replay identity uniqueness by candidate and transactionally migrates the legacy global-unique registry so root+r2 can share one authenticated capture replay identity;
- #230: attributes raw candidate-local terminal runner failures to the `evaluate-research` dashboard stage without changing checkpoint accounting;
- #232: authenticates persisted paper execution attempts/fills during restart, reconciles deterministic IDs and fill totals, rejects orphaned/inconsistent history, and enforces fill -> attempt identity at write time.

PR #232 merged as `09e5c93db64ede19ec6ad02ac642defc96176c27`. Post-merge main CI `35596674099` passed compile, Ruff, mypy, full pytest, and research smoke. Research Dashboard refresh `35586218717` remains trusted and renders the failed r2 attempt as `evaluate-research` / NOT COUNTED.

---

## 7. Exact handoff / next action

1. Keep live trading disabled and risk limits unchanged.
2. Use `docs/superpowers/plans/2026-09-21-historical-directional-learning.md` as the primary plan.
3. Preserve retired V4, r1, and r2 evidence as touched/auditable history.
4. Treat verified Slices B, C, and D as the immutable source/dataset/evaluation boundary for historical learning.
5. Run bounded touched-development experiments on real public-mainnet historical corpora and persist reproducible reports.
6. Report performance by market, regime, direction, horizon, time fold, and shared-versus-coin variant without relabeling historical research as untouched.
7. Add more complex supervised models only if they materially beat the transparent baseline under the same chronological protocol.
8. Freeze any promising candidate and every relevant config/data/feature/decision artifact before future clean validation.
9. Keep model selection, costs, and thresholds confined to train/validation; untouched test and future validation remain protected.
10. Freeze any promising model/config before new clean validation; never relabel historical development data as untouched.
11. Advance toward live trading only after every locked promotion gate and explicit user authorization.

---

## 8. What not to do

- Do not use Hyperliquid testnet.
- Do not add live wallet/order/transfer/withdrawal behavior.
- Do not manually cancel/retry/extend/backfill protected V4 or research economics to accelerate results.
- Do not relabel touched evidence as untouched.
- Do not weaken provenance, overlap, completeness, replay, attestation, authentication, daily caps, or rollout-verifier gates.
- Do not use nominal scheduler timing as a substitute for actual run/job/session authority.
- Do not trust this file over newer live repository evidence.


## 9. Historical-learning frontier sync — 2026-09-21

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

Active development frontier: PR #256 adds one fixed shallow nonlinear tree challenger behind the same four-block stability gate. It remains touched research and is not a promotion candidate unless the verified exact-head evidence justifies that status.

Current economic conclusion: the system is correctly rejecting attractive-looking but unstable historical patterns. No merged historical learner has yet demonstrated repeatable cost-adjusted edge sufficient for promotion. The next priority is broader trustworthy history and reproducible challenger comparison, not weakening NO_TRADE or validation gates.



## 10. Frozen prospective HYPE clean-validation campaign — 2026-09-22

This is the current primary research frontier and supersedes older historical-only handoff text where they conflict.

Frozen candidate:

- `hype-down-bearish-near-basket-long-4h-v1`;
- HYPE, 1h anchors, `down/bearish/near_basket`, LONG, 4h horizon;
- one-position-per-market occupancy;
- fixed modeled costs: 7 bps round-trip fee, 5 bps round-trip slippage, 1 bp/hour funding reserve;
- historical discovery remains touched and non-promotional.

Frozen clean-validation plan:

- start: 2026-09-23 00:00:00 UTC;
- first expected anchor: 2026-09-23 00:59:59.999 UTC;
- end: 2026-11-07 00:00:00 UTC;
- finalization not before: 2026-11-07 04:00:00 UTC;
- 1,080 expected hourly anchors;
- >=972 captured observations (90%);
- >=80 settled executable trades;
- four chronological blocks, >=15 settled trades per block;
- overall mean modeled net return >0;
- every block mean modeled net return >0;
- passing status means candidate-review eligibility only, never automatic promotion.

Frozen runtime/control plane:

- observer/report/evidence Python revision is permanently pinned for this campaign to `0131fccdb09a2b9ba959dd5785ea213a6297f719`;
- the workflow checkout must remain that exact SHA;
- the cumulative runtime attestation must remain present and match the candidate/plan/source revision;
- capture cron remains `3,8,13 * * * *` UTC;
- 15-minute maximum entry-candle age, paper mode, canonical Hyperliquid mainnet endpoints, state artifact identity, evidence-root path, concurrency, timeout, read-only permissions, and retention are bound into a pre-cutover cumulative control-plane attestation;
- post-cutover missing or conflicting runtime/control-plane attestation fails closed.

Evidence continuity/finalization:

- cumulative state restore is mandatory after cutover;
- no new observations are admitted after the frozen validation end;
- exact 4h outcome settlement may continue after the observation window;
- per-cycle frozen validation report and workflow-only recoverability health are immutable run artifacts;
- health may mark the campaign degraded or mathematically irrecoverable but may not alter strategy logic;
- state/report/health/lineage artifacts are preserved before any irrecoverable failure turns the workflow red;
- exactly one canonical `finalization.json` may be created after the finalization boundary and only when no due exact-horizon settlement is overdue;
- finalization binds state digest, evidence digest, final economics, block results, runtime attestation, source SHA, and control-plane attestation;
- later state/economic/finalization drift fails closed rather than creating a second verdict.

During the clean campaign, do **not** tune this candidate from emerging evidence. No feature/context/direction/horizon/cost/occupancy/threshold/runtime/control-plane changes are allowed for this campaign. Unrelated research may continue only if it cannot contaminate the campaign.

Live trading remains disabled and all existing paper/shadow/risk/promotion/explicit-authorization gates remain unchanged.
