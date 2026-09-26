# Cocomelon Locked Decisions

This file records decisions that should not be casually re-litigated in later chats. A decision can change only through an explicit user instruction or a documented evidence-based revision.

## D-001 — Hyperliquid mainnet only

**Decision:** Do not use Hyperliquid testnet at any stage.

**Why:** Testnet has different liquidity, order books, participants, and behavior. Strategy validation must reflect the real market.

**Implementation consequence:** Use mainnet market data for development, backfill, recording, paper trading, and shadow trading. Runtime configuration rejects testnet hostnames.

## D-002 — Internal paper trading before real capital

**Decision:** Validate on real Hyperliquid mainnet data with our own paper/shadow execution simulator, then move directly to gated mainnet live execution when criteria pass.

**Why:** We need realistic market conditions without risking capital before the system has evidence of an edge.

## D-003 — Autonomous full trade lifecycle

**Decision:** The final system chooses the market, LONG/SHORT/NO TRADE, entry, stop, position size, management actions, and exit without per-trade human approval.

**Boundary:** Autonomous trading remains constrained by hard risk and live-mode gates. The bot does not autonomously fund the account or change its own hard safety limits.

## D-004 — Intraday focus

**Decision:** V1 targets trades typically held from roughly 10 minutes to 6 hours.

**Clarification:** This is a design horizon, not a forced timer. The system can exit earlier when invalidated and can remain longer when the thesis/risk state permits.

## D-005 — Whole-market funnel, not full deep analysis everywhere

**Decision:** Discover broadly, filter cheaply, rank, then deeply monitor a bounded dynamic shortlist.

**Why:** It preserves broad opportunity coverage without wasting compute/storage or chasing illiquid markets.

## D-006 — Initial risk per trade is 0.25%

**Decision:** Planned V1 account risk per trade is 0.25% of equity.

**Additional limits:** 0.75% aggregate planned open risk, 1% daily realized-loss lockout, 3% rolling weekly drawdown lockout, and cooldown after three consecutive losing trades.

**Why:** The system must earn the right to take more risk through evidence rather than starting aggressive.

## D-007 — Leverage does not define risk

**Decision:** Position size is calculated from equity, stop distance, liquidity, and risk budget. Leverage is only a means of obtaining notional exposure within venue constraints.

## D-008 — Python first; no Solidity in V1

**Decision:** Python is the primary implementation language.

**Why:** The target is HyperCore perp trading through Hyperliquid's API/SDK, plus data science, backtesting, and ML. HyperEVM/Solidity is unnecessary for this problem.

**Revisit only if:** a future feature genuinely requires an onchain HyperEVM smart contract.

## D-009 — Free/public sources first

**Decision:** Initial build must not require paid market-data or infrastructure providers.

**Consequence:** Requester-pays historical S3 archives are optional, not default. Begin collecting our own mainnet microstructure history.

## D-010 — Explainable baseline before ML control

**Decision:** V1 starts with deterministic strategy/risk baselines. ML appears later as a challenger that must beat the champion.

**Why:** Otherwise we cannot tell whether a model has learned an edge or simply fit noise/data leakage.

## D-011 — Multiple strategy families

**Decision:** Baseline research includes trend, breakout, mean reversion, funding/OI context, and order-flow/microstructure components.

**Clarification:** Funding/OI and order flow can act as context/vetoes rather than always creating standalone trades.

## D-012 — NO TRADE is a first-class decision

**Decision:** The bot is not required to trade. It may scan the entire eligible universe and take zero positions.

**Why:** Opportunity selectivity is part of the edge.

## D-013 — Do not fabricate historical order books

**Decision:** Candle data cannot be transformed into invented L2/trade history and used to claim order-flow profitability.

**Consequence:** Microstructure strategies require actual recorded/reliably sourced order-book/trade events.

## D-014 — Paper and live execution share an interface

**Decision:** Strategy/risk components submit approved order plans to an execution abstraction. Paper and eventual Hyperliquid live adapters implement the same interface.

**Why:** Going live should not require rewriting the trading brain.

## D-015 — Separate operational and high-volume storage

**Decision:** SQLite stores state/journal/control records. Parquet or equivalent columnar files store large market-event/feature datasets.

## D-016 — No averaging down or martingale

**Decision:** V1 cannot add size to a losing position and cannot increase size because previous trades lost.

## D-017 — Learning is champion/challenger, not self-modification

**Decision:** The live champion remains frozen. New models train offline and are promoted only after reproducible validation.

## D-018 — Live mode requires explicit promotion and dual activation

**Decision:** Live execution remains disabled by default and requires both objective promotion gates and explicit user authorization. Runtime activation must require at least two independent signals, not one accidental flag.

## D-019 — Dedicated API/agent wallet for live runtime

**Decision:** When live execution is finally enabled, the bot runtime uses a dedicated Hyperliquid API/agent wallet and does not store the master wallet private key.

## D-020 — Build reliability before sophistication

**Decision:** Data integrity, replay, accounting, risk, and paper execution are built before ML or live execution.

**Why:** A sophisticated strategy on bad data/accounting is worse than a simple strategy we can trust.

## D-021 — Phase 3 raw stream log is durable JSONL; Parquet compaction is offline

**Decision:** The always-on Phase 3 WebSocket collector writes fsynced, append-only, rotating JSONL segments as the trusted raw/normalized stream log. Do not add PyArrow to the always-on runtime merely to produce Parquet during ingestion.

**Why:** JSONL keeps crash recovery and auditing simple, preserves exact event provenance, and keeps the free baseline lightweight. A large columnar dependency is more appropriate in an offline compaction/research job than in the liveness-critical collector.

**Compatibility with D-015:** Parquet (or an equivalent columnar format) remains the preferred large analytical dataset format. A later data/replay slice must compact validated JSONL partitions into columnar files before large-scale research/feature workloads rely on them. Renaming JSONL files to `.parquet` is forbidden.

## D-022 — Phase 6 risk authority is fixed, conservative, and Decimal-deterministic

**Decision:** Phase 6 is the sole new-exposure risk authority. Strategy conviction cannot increase risk. Default V1 constraints are a 0.50% correlation-bucket planned-risk cap, 3x gross system leverage ceiling or lower venue maximum, at most 50% of currently available margin for a new position, at most 10% of the weaker visible 25-bps side depth, and liquidation distance beyond the stop and at least 2x stop distance.

**Arithmetic consequence:** Authoritative risk evaluation runs in a fixed 28-digit Decimal context. Risk-budget-to-notional division rounds downward so repeating Decimal quotients cannot exceed the approved risk budget by a rounding unit.

**Boundary:** Same-market add-on exposure, score-proportional sizing, martingale/loss-recovery sizing, order placement, wallet/signing, exchange account APIs, fill simulation, ML control, and live execution remain outside the risk package.

**Why:** Risk decisions must be reproducible in replay, conservative under numerical edge cases, and impossible for strategy confidence or ambient process Decimal settings to relax.

## D-023 — Dual-lane research with frozen promotion evidence

**Decision:** Keep the active V4 Phase 9 validation lane frozen and performance-blind while adding a separate adaptive research lane for fast failure detection and challenger iteration.

**Why:** Final promotion evidence and rapid research have incompatible information requirements. Repeated economic inspection is useful for rejecting weak research candidates quickly, but touched observations cannot remain untouched evidence for a promotion claim.

**V4 preservation:** The research lane cannot reveal, reconstruct, tune from, retry, reclassify, or mutate V4 interim economics or `v4-mainnet-corpus`. V4 strategy/risk/execution/evaluator/schedule semantics remain unchanged.

**Non-reconstructability consequence:** Until V4 has a terminal immutable one-shot result, research economics may be computed only from source-time intervals that are provably disjoint from every actual V4 acquisition interval, including failed/diagnostic runs. Candidate distinctness alone is not sufficient. Ambiguous or overlapping research batches fail closed as `REJECTED_CONTAMINATION`.

**Lineage consequence:** Every research candidate has immutable `family_id`, parent/ancestor lineage, and an effective touched-period set equal to the union of its own and all ancestor touched intervals. Renaming or changing candidate digests never resets touched history.

**Fast-failure consequence:** Research economic futility may reject a candidate after at least 20 closed trades under the precommitted Bayesian rule in `docs/superpowers/specs/2026-08-31-dual-lane-sequential-research-design.md`. Positive early results cannot promote a candidate; `RESEARCH_PROMISING` only permits freezing a challenger for future clean validation.

**Clean-validation consequence:** A frozen challenger may begin untouched validation only after its freeze timestamp and a 6-hour embargo following the latest inherited touched interval. Promotion remains governed by the existing untouched OOS/walk-forward/bootstrap gates.

**Safety:** Both lanes remain paper/shadow only at this stage. Live orders remain disabled and Phase 10 remains blocked until the authoritative promotion gates pass.


## D-024 — Retire the revealed V4 baseline and move development to touched research

**Decision:** The V4 baseline `v4-baseline-4h-thesis-expiry` is retired from future scheduled economic acquisition and from automatic Phase 9 one-shot evaluation. Its already-running acquisition at the time of this decision must finish naturally; it is not cancelled, retried, extended, or outcome-conditioned.

**Why:** The user explicitly authorized revealing the interim V4 economics after the corpus reached 100 closed paper trades. That reveal intentionally ended the sample's performance-blind/untouched status. The revealed 100-trade snapshot showed negative gross and net expectancy: approximately `-537.62` gross PnL, `-629.91` net PnL, mean net R about `-0.298`, profit factor about `0.44`, and realized closed-trade maximum drawdown about `7.80%`. More automatic promotion evidence for the exact frozen baseline is therefore not economically justified.

**Evidence identity:** The disclosed snapshot is bound to V4 corpus artifact `10497424756` and is recorded in `docs/v4-baseline-retirement.json`. Later V4 cohorts are not used to retune the already frozen r2 quality thresholds.

**D-023 revision:** D-023 remains the governing design for touched research and future clean validation, but its performance-blind preservation clause no longer applies to the retired V4 baseline after the explicit reveal. The disclosed V4 sample is permanently **TOUCHED / DEVELOPMENT-ONLY** and can support hypothesis generation, never promotion or an untouched OOS claim.

**Research consequence:** Development proceeds through immutable research candidates. `research-r2-short-trend-quality-v1` is pinned to the strategy seam introduced by PR #205 and registered through the authoritative research registry. Positive research remains non-promotional and must still satisfy the precommitted research thresholds before a challenger can be frozen.

**Future validation consequence:** Any future promotion candidate requires a new clean validation sample collected only after that candidate is frozen and after all applicable touched-data/embargo rules are satisfied. The disclosed V4 corpus and any strategy decisions derived from it cannot be relabeled as untouched evidence.

**Safety:** Risk limits are unchanged. Live orders remain disabled. Phase 10 remains blocked. Historical V4 artifacts, provenance, curator logic, and overlap authority remain available for audit; retirement only stops future automatic acquisition/evaluation for the failed touched baseline.

## D-025 — Historical two-sided learning becomes the primary research architecture

**Decision:** Cocomelon’s primary research architecture is a direction-neutral historical learning system that studies point-in-time market states and estimates conditional forward opportunity for LONG, SHORT, and NO_TRADE. `research-r2-short-trend-quality-v1` remains immutable and auditable as a bounded touched short-side experiment, but it is no longer the product architecture or the sole development gate.

**Why:** The user clarified that the intended system must learn how each coin behaves and choose direction from evidence rather than begin from a permanent directional veto. The revealed V4 baseline failed to demonstrate edge, satisfying the Phase 9 exit condition in the explicit honest-failure sense already allowed by `BUILD_ORDER.md`. Continuing to make a hand-filtered short-only challenger the sole path would overfit the product architecture to one touched development subset.

**Historical-data consequence:** Offline research may backfill trustworthy public Hyperliquid mainnet candle and funding history within real source limits and combine it with the project’s own authenticated recorded history. The pipeline must preserve provenance, respect request/source depth limits, detect gaps, and never fabricate historical L2/order-flow/OI fields that were not actually sourced.

**Learning-target consequence:** Historical feature rows contain only information available at their anchor timestamp. Future observations may appear only in explicit outcome labels. The initial substrate records both LONG and SHORT forward returns at predeclared horizons; later cost models convert them into comparable net targets. NO_TRADE is selected when neither side demonstrates sufficient expected edge after costs and uncertainty.

**Validation consequence:** Learning uses chronological train/validation/test partitions, embargo where required, and walk-forward evaluation. Random temporal shuffling, future-fitted normalization, test-set hyperparameter selection, or any other lookahead leakage is prohibited. Historical backtests are touched development evidence unless a candidate was frozen before the relevant untouched period.

**Phase consequence:** Phase 10 offline learning engineering is now active. This opens dataset, feature, model-training, and challenger-evaluation work only. It does not authorize live trading or weaken promotion gates. Any model intended for promotion still requires a frozen candidate, clean future validation, cost-complete OOS/walk-forward evidence, the existing >=500 closed mainnet paper-trade and >=45-day shadow requirements, clean risk/integrity state, and explicit user authorization before live capital.

**Risk consequence:** Models may rank or choose LONG/SHORT/NO_TRADE, but they may not alter hard risk limits, control leverage directly, bypass eligibility, or call live execution APIs.



## D-026 — NO_TRADE and temporal stability are mandatory economic baselines

**Decision:** A historical learning policy must not trade merely because it is the best available candidate. NO_TRADE has zero realized return before opportunity cost and therefore dominates any validation policy whose realized net mean is non-positive after modeled costs.

**Stability consequence:** Aggregate validation profitability is insufficient. Before a horizon may trade, its selected threshold must also satisfy the configured chronological validation-stability rule across multiple contiguous validation blocks with the required minimum trade count. A candidate that looks profitable only because one subperiod overwhelms a losing subperiod is rejected.

**Model consequence:** This rule applies uniformly to transparent conditional baselines, regularized ridge learners, horizon-specific variants, and later nonlinear challengers. A more complex model does not receive weaker validation standards.

**Historical-data consequence:** Recent public candle/funding history remains valid for bounded touched research. Deeper history may use deterministic candles reconstructed from official Hyperliquid node fill archives only after provenance/integrity checks and exact overlap reconciliation against native recent candles. Requester-pays archive acquisition remains optional and acknowledgement-gated; no paid transfer is automatic.

**Promotion consequence:** A model that abstains everywhere has demonstrated safety/selectivity, not trading edge. It must not be promoted until a frozen candidate later demonstrates positive cost-complete evidence under the required future clean validation and paper/shadow gates.



## D-027 — Frozen prospective HYPE validation is observational, not tunable

**Decision:** The touched historical candidate `hype-down-bearish-near-basket-long-4h-v1` is admitted to one predeclared prospective-clean evidence campaign. Its candidate logic and evidence-collection semantics are frozen before the clean window. Emerging prospective results may be observed but may not be used to retune this campaign.

**Candidate freeze:** HYPE, 1h anchor, exact context `down/bearish/near_basket`, LONG, 4h horizon, one-position-per-market occupancy, and the fixed modeled fee/slippage/funding assumptions are immutable for this campaign.

**Validation freeze:** The clean window is 2026-09-23 00:00:00 UTC through 2026-11-07 00:00:00 UTC, with finalization no earlier than 2026-11-07 04:00:00 UTC. The frozen plan requires 1,080 expected hourly anchors, >=90% capture (>=972 observations), >=80 settled executable trades, four chronological blocks with >=15 settled trades each, overall mean modeled net return >0, and every block mean modeled net return >0.

**Runtime freeze:** Observer/report/evidence Python for this campaign is pinned to git revision `0131fccdb09a2b9ba959dd5785ea213a6297f719`. A cumulative runtime attestation binds the candidate spec, validation plan, and source revision. Missing or conflicting runtime identity after cutover fails closed.

**Control-plane freeze:** The campaign's capture-critical cron, attempt minutes, 15-minute stale-anchor limit, cumulative state artifact/evidence-root identity, non-cancelling concurrency, timeout, paper mode, canonical Hyperliquid mainnet endpoints, read-only permissions, and artifact retention are bound into a cumulative pre-cutover control-plane attestation. Materially changing those settings requires a new campaign rather than silently mutating this one.

**Continuity consequence:** Post-cutover evidence requires restored cumulative state. State resets, wrong campaign identity, conflicting runtime/control-plane state, post-window observations, or other integrity conflicts fail closed. There is no protected-interval retry/backfill mechanism that can turn a failed or incomplete clean campaign into a success.

**Recoverability consequence:** Workflow-only monitoring may report pre-validation, healthy, degraded, or mathematically irrecoverable capture state. Monitoring does not alter the frozen candidate. An irrecoverable campaign is allowed to fail honestly; audit artifacts are preserved before the workflow turns red.

**Finalization consequence:** Exactly one canonical terminal finalization receipt is predeclared. It may be created only after the frozen finalization boundary and only when no due exact-horizon settlement is overdue. It binds state digest, evidence digest, final economic status/counts/returns/block results, frozen runtime identity, and frozen control-plane identity. Later state/economic drift or conflicting finalization state fails closed rather than producing a second verdict.

**Interpretation:** `eligible_for_candidate_review` is the strongest possible output of this campaign. It is not promotion eligibility and does not authorize live capital. All existing >=500 mainnet paper-trade, >=45-day shadow, risk/integrity, and explicit-live-authorization gates remain mandatory.

**Development consequence:** During the clean campaign, unrelated research may continue only if it cannot contaminate this evidence. Any materially different hypothesis must be frozen as a new candidate and collect a new future clean sample.


## D-028 — V1 capture failure is preserved; HYPE V2 restarts clean validation

**Decision:** The original prospective HYPE V1 campaign remains immutable under D-027. Its predeclared GitHub Actions capture transport failed to create a scheduled observer run through the first post-cutover `:03/:08/:13` attempts on 2026-09-23. The unmerged pre-cutover transport-repair PR #363 was closed after the V1 cutover passed because merging it would have violated its own pre-cutover attestation invariant. V1 is not retroactively repaired, backfilled, or relabeled.

**V2 identity:** A fresh candidate identity, `hype-down-bearish-near-basket-long-4h-v2`, preserves the V1 economic hypothesis exactly: HYPE, 1h anchors, context `down/bearish/near_basket`, LONG direction, 4h horizon, one-position-per-market occupancy, discovery lineage, and fixed fee/slippage/funding assumptions. The new identity exists only to bind a fresh future clean boundary and independent campaign state.

**V2 validation freeze:** V2 begins 2026-09-25 00:00:00 UTC and runs for 45 calendar days through 2026-11-09 00:00:00 UTC, with finalization no earlier than 2026-11-09 04:00:00 UTC. The economic qualification thresholds remain identical to V1: 1,080 expected hourly anchors, >=90% capture, >=80 settled executable trades, four chronological stability blocks with >=15 settled trades each, positive overall mean modeled net return, and positive mean modeled net return in every block.

**V2 source freeze:** V2 observer/report/evidence runtime is pinned to merged revision `d15971eb22cec7b6fb2025bbb338c9d6d677eb63`. The scheduled workflow may not substitute moving `main` source for that revision.

**V2 transport freeze:** Capture uses redundant off-peak GitHub schedule starts at UTC minutes 43, 48, and 53. Scheduled jobs pre-warm toward the next hourly minute 03 protected attempt. If a delayed schedule starts after the protected attempt, it may proceed only while the existing 15-minute stale-anchor ceiling can still be satisfied; otherwise it fails closed. Concurrency is non-cancelling and serial, job timeout is 30 minutes, state/evidence identities are V2-specific, execution remains paper-only, Hyperliquid endpoints remain canonical mainnet, permissions remain read-only, and artifacts retain for 90 days.

**Continuity consequence:** V2 state is independent from V1. Runtime and control-plane attestations must exist before V2 cutover. After cutover, missing state/runtime/control-plane identity fails closed. Duplicate redundant attempts may be idempotent, but no historical anchor backfill is allowed.

**Interpretation:** The transport change is not evidence that the economic hypothesis improved. V2 must earn its own clean result. `eligible_for_candidate_review` remains non-promotional; all >=500-paper-trade, >=45-day-shadow, risk/integrity, and explicit live-authorization gates remain mandatory.


## D-029 — HYPE V3 moves clean capture off GitHub schedule delivery

**Decision:** V1 and V2 remain immutable evidence campaigns under D-027/D-028. V2 is not rewritten or backfilled. After V2 cutover, GitHub created scheduled run `36103594834` at 2026-09-25 06:36 UTC, well outside its frozen off-peak pre-warm phases; the workflow correctly failed `PREWARM_SCHEDULE_TOO_LATE_FOR_FRESH_CAPTURE` before touching evidence. That operational failure is preserved as transport evidence, not interpreted as candidate economics.

**V3 identity:** `hype-down-bearish-near-basket-long-4h-v3` preserves the same HYPE economic hypothesis, discovery lineage, direction, 4h horizon, one-position-per-market occupancy, modeled costs, and qualification thresholds. V3 has a fresh campaign/spec/plan identity solely because its capture transport and clean boundary are different.

**V3 validation freeze:** V3 begins 2026-09-26 00:00:00 UTC and runs through 2026-11-10 00:00:00 UTC, with finalization no earlier than 2026-11-10 04:00:00 UTC. It still requires 1,080 expected hourly anchors, >=90% capture, >=80 settled executable trades, four chronological stability blocks with >=15 settled trades each, positive overall mean modeled net return, and positive block means.

**Source freeze:** V3 observer/report/evidence/dispatch-queue source is pinned to merged revision `298723c52d6a3b09839d05451d3d7db9753815bf`, which contains the V3 primitives plus the tested pure rolling-dispatch queue logic. Moving `main` source is not an acceptable substitute.

**Transport freeze:** V3 has no scheduled trigger. A pre-cutover push bootstrap creates a bounded queue of four future `workflow_dispatch` capture runs. Every capture target is exactly UTC minute 03. Future runs are created hours ahead, elect the lowest covering run ID as duplicate leader, hand off ten minutes before target, enforce the unchanged 15-minute source-age ceiling at execution, and replenish the next four targets only when their own turn arrives. Dispatch creation retries only transient GitHub 500/502/503/504 failures and verifies that the future queue is visible before proceeding.

**Continuity consequence:** Transport preparation is separated from economic evidence. Queue receipts are explicitly non-economic. Only the leader may reach the observer job. Cumulative V3 state, runtime attestation, control-plane identity, exact source revision, candidate identity, and validation plan remain fail-closed. There is no anchor backfill.

**Permission consequence:** V3 requires `actions: write` only so its frozen workflow can create future `workflow_dispatch` runs. Repository contents remain read-only, execution remains paper-only, Hyperliquid endpoints remain canonical mainnet, and live trading remains disabled.

**Interpretation:** V3 is a capture-reliability restart, not a retune. V1/V2 operational outcomes remain auditable, and no prospective interim economics are used to choose or modify V3.


## D-030 — Settled trades feed future challengers through a quarantined learning ledger

**Decision:** Settled paper and eventual live execution outcomes may be copied into an append-only learning-evidence ledger as soon as they exist, but the active strategy being evaluated must never be retuned from its own still-open validation campaign.

**Prospective quarantine:** A prospective campaign outcome is bound to its exact candidate spec, campaign, observation, feature snapshot, context, modeled cost, and settled net return. Its `research_eligible_at_ms` is the campaign's predeclared `finalization_not_before_ms`. The record may exist before then for provenance and continuity, but challenger research must not consume it before that boundary.

**Execution feedback:** Closed paper/live execution trades may also enter the same ledger, preserving actual gross PnL, fees, funding cash PnL, entry/exit slippage, net PnL, and net-R. Every execution record requires an explicit research-eligibility timestamp no earlier than trade close. Live execution evidence does not automatically rewrite the strategy controlling capital.

**Metric separation:** Modeled prospective return fractions and actual execution PnL fields are mutually exclusive record families. The system must not silently treat modeled return, account return, net-R, and realized cash PnL as interchangeable targets.

**Evolution consequence:** Learning is continuous at the evidence layer, not by mutating a running candidate after each trade. Eligible evidence may train or select a future challenger; that challenger must receive a new identity and pass its own chronological and prospective gates before any promotion decision.


## D-031 — Challenger training snapshots must exclude quarantined learning evidence

**Decision:** Future model fitting and challenger selection must consume a deterministic learning-dataset snapshot, not the raw outcome ledger directly.

**Eligibility boundary:** A snapshot includes only records whose `research_eligible_at_ms <= as_of_ms`. Records still under prospective or execution quarantine remain excluded from all training partitions.

**Audit boundary:** Every snapshot binds the full ledger state digest, eligible record IDs, quarantined record IDs, candidate IDs, and separate prospective-paper, paper-execution, and live-execution partitions. Adding even a still-quarantined record changes the dataset identity, so later research can prove exactly what was known and what was excluded.

**Metric consequence:** Prospective modeled-return evidence, paper execution evidence, and live execution evidence remain separate typed partitions. Downstream research must explicitly choose how to use them rather than silently pooling incomparable targets.

**Evolution consequence:** A challenger may learn only from an eligible snapshot and must retain that snapshot ID in its lineage. The active candidate remains immutable during its own clean campaign.

## D-030 — Retire Prospective HYPE experiment and restore continuous paper-trader semantics

**Date:** 2026-09-26

**Decision:** Retire the Prospective HYPE V1/V2/V3 experiment family from active operation. Remove its scheduled observers, audits, readiness/lineage/blind-monitor jobs, V2 clean workflow, V3 capture/heartbeat rolling queue, and cutover machinery. Preserve historical artifacts and prior decisions only as audit history.

**Reason:** The experiment's periodic/hourly observation semantics do not represent the intended product. Cocomelon is specified to continuously scan the eligible Hyperliquid mainnet perp universe and enter paper positions when a valid strategy setup passes independent risk and execution checks. A once-per-hour HYPE-only experiment can miss intraday opportunities and must not be confused with the operational paper trader.

**Operational consequence:** Prospective HYPE artifacts are historical/non-current. Future paper operation must be driven by the ordinary scanner -> shortlist -> strategy -> risk -> paper-execution runtime. Research and learning may consume properly authenticated ordinary paper evidence without reviving the retired HYPE experiment.

**Integrity consequence:** Retiring the experiment does not relabel its touched/prospective evidence, does not convert modeled outcomes into actual paper fills, and does not weaken risk or promotion gates.

**Safety consequence:** Execution remains paper/shadow only. Live trading remains disabled and still requires all objective promotion gates plus explicit user live authorization and capital amount.

**Supersedes:** D-029 only as active operational authority. D-029 remains historical documentation of the retired V3 protocol.

## D-031 — Continuous ordinary paper trader replaces periodic prospective experiments

**Date:** 2026-09-26

**Decision:** Operate paper trading through the ordinary mainnet scanner -> dynamic shortlist -> strategy -> independent risk -> paper execution lifecycle. The active paper runtime is not a fixed-hour candidate experiment and is not tied to HYPE.

**Runtime behavior:**

- scan the native Hyperliquid perp universe from fresh mainnet market context;
- maintain a bounded deep shortlist (initially 20, configurable) while pinning every open position;
- consume mainnet active-asset context, L2, trades, and 1m/5m/15m candles continuously;
- evaluate the existing deterministic strategy stack on the frozen V1 15-minute decision cadence;
- allow LONG, SHORT, or NO_TRADE and submit exposure only after independent risk approval;
- manage stops, thesis exits, funding, marks, partial/reduce-only exits, and accounting from fresh market events;
- persist paper execution/journal/evaluation state and restart lineage across long-running worker handoffs;
- periodically re-rank the universe without changing risk limits or converting the runtime into a research experiment.

**Operational hosting:** GitHub Actions may be used as a rolling paper-only worker. Long sessions publish durable state, then dispatch the next worker. A lightweight watchdog may recover a broken chain; the watchdog is operational continuity, not an economic observation cadence.

**Evidence:** ordinary paper fills/trades produced by this runtime are a separate authenticated evidence family. Retired V4, scheduled research replay, retired Prospective HYPE, and learned-candidate clean/shadow evidence remain separate.

**Safety:** the runtime must fail closed on corrupted/missing restart lineage, stale/inconsistent execution state, or non-paper execution configuration. Live trading remains disabled and still requires every locked promotion gate plus explicit user live authorization and capital amount.

## D-032 — Continuous paper closures feed a separate authenticated learning state

**Date:** 2026-09-26

**Decision:** Completed ordinary continuous-paper worker artifacts may feed a dedicated append-only learning state only after the runtime has an authenticated decision-time feature-capture activation boundary.

Rules:

- the legacy pre-feature worker is never backfilled into learning;
- the runtime persists `learning_feature_capture_started_at_ms` across worker handoffs;
- trades opened before that boundary are explicitly excluded from continuous-paper learning;
- every trade opened at or after the boundary must resolve to an authenticated decision-time `FeatureSnapshot`, otherwise ingestion fails closed;
- completed-worker `session-summary.json`, journal trade count, feature-store count, and feature-store digest must reconcile before admission;
- repeated cumulative-worker ingestion is idempotent: each execution learning record uses the trade close time as its stable research-eligibility timestamp;
- continuous-paper learning state is source-separated from scheduled-research cumulative state so source-specific lineage is not blurred or raced;
- readiness may be evaluated automatically, but this state is research-only and cannot directly retune the active trader, promote a candidate, or authorize execution.

The active paper strategy, risk limits, execution model, and live-trading authority are unchanged.

**LIVE TRADING: DISABLED.**

