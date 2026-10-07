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

## D-032 — Attribute continuous paper learning at entry time

**Date:** 2026-09-26

**Decision:** Continuous-paper execution outcomes may feed a research-only learning state only when the trade carries immutable entry-time runtime lineage. Attribution is recorded when the opening fill creates the paper position, not when a later worker exports or closes the trade.

**Lineage:** Every new lineage-capable opening binds its opening plan, feature snapshot, market, opened-at timestamp, exact GitHub Actions run ID, run attempt, and worker head SHA. The worker SHA is used as the candidate-spec lineage and the exact worker run/attempt as the campaign lineage. The stable candidate family is `continuous-paper-ensemble-v1`.

**Legacy boundary:** Existing/restored trades that predate this entry-time lineage are not backfilled or guessed. They are explicitly skipped by the continuous-paper learning sync. A trade whose market, feature snapshot, replay identity, or opened-at timestamp conflicts with its opening lineage fails closed.

**Feature boundary:** A learning record requires the authenticated decision-time `FeatureSnapshot` used by the opening. The snapshot must match the trade market and must have been known no later than the trade open. Only the matched snapshot is copied into the durable learning feature store.

**Economic target:** The learning record uses the existing typed `paper_execution` family and preserves actual realized gross PnL, entry/exit fees, funding cash PnL, entry/exit slippage, net PnL, and net-R. Research eligibility begins no earlier than the authenticated trade close.

**Producer boundary:** Completed lineage-capable continuous-paper workers are authenticated by exact run identity and exact artifact digest before ingestion. Their learning evidence is initially kept in a separate 90-day `continuous-paper-learning-state`; it is not silently merged into scheduled-research learning lineage.

**Authority:** This is evidence capture only. The sync may audit structural learning readiness, but it does not train in the producer workflow, does not mutate the active trading strategy, does not grant promotion authority, and cannot enable execution.

**LIVE TRADING: DISABLED.**

## D-033 — Continuous paper outcomes use an isolated frozen research learning cycle

**Date:** 2026-09-26

**Decision:** Authenticated continuous-paper execution outcomes remain in their separate `continuous-paper-learning-state` and may run the existing frozen research learning cycle without being merged into the scheduled-research learning lineage.

**Training gate:** The cycle inherits the existing immutable chronological capacity requirements: at least 200 settled training records followed by exactly 20 validation records, with the existing stability-block and feature-completeness checks. Before that capacity exists, the correct result is `not_ready`, not relaxed thresholds or synthetic evidence.

**Model boundary:** The cycle may evaluate the existing transparent grouped-mean baseline and fixed shallow-tree challenger against authenticated continuous-paper features and realized paper net-R. It may not rewrite the active continuous-paper strategy, alter risk limits, select a live strategy, or place orders.

**Promotion boundary:** Continuous-paper cycle artifacts are research-only and non-promotional. Even a development-qualified model receives no automatic candidate freeze, clean-validation admission, shadow admission, or execution authority from this workflow. Any later promotion path must preserve a new immutable candidate identity and the existing prospective/clean gates.

**Lineage boundary:** The cycle authenticates the exact successful continuous-paper learning-sync run and exact state artifact digest, re-verifies persisted ledger/feature counts and state digests, and binds its own artifact name to the exact upstream sync run/attempt.

**Legacy boundary:** Trades without D-032 entry-time attribution remain excluded. No historical or restored position is backfilled merely to increase sample size.

**LIVE TRADING: DISABLED.**



## D-034 — Directional intelligence must be context-aware, not side-suppression by recent PnL

**Date:** 2026-10-06

**Decision:** Cocomelon must not reduce, disable, or penalize LONG or SHORT exposure merely because that direction has produced more recent losses in aggregate. Direction is an output of market context, not a static preference.

**Required behavior:** Strategy research and learning must evaluate the conditions surrounding each decision — including trend/structure, momentum, volatility/regime, liquidity/spread/depth, funding, order-flow or book evidence when genuinely available, and recent price behavior — and learn which combinations support LONG, SHORT, or NO_TRADE. Weak setups are filtered because their context lacks edge, not because their direction is unpopular.

**Evaluation consequence:** Performance must be segmented by direction *and* relevant market context/regime. A side-level loss statistic is diagnostic evidence only; it is not sufficient authority for a trading rule. Any directional restriction must be backed by reproducible context-conditioned net expectancy after realistic costs and must pass the same chronological/OOS/shadow gates as any other strategy change.

**Learning consequence:** Historical and continuous-paper learning should compare winners and losers under comparable market states so Cocomelon can distinguish “bad long/short setup here” from “longs/shorts are bad.” NO_TRADE remains first-class when neither side has sufficient expected edge.

**Goal:** Build a trader that can identify when a market favors LONG, when it favors SHORT, and when the correct action is NO_TRADE, rather than chasing recent side-level win/loss streaks.

**Safety:** This decision does not relax independent risk limits, evidence integrity, promotion gates, or the live-trading prohibition.


## D-035 — Freeze the first skipped-opportunity context candidate before prospective reuse

**Date:** 2026-10-06

**Decision:** The first continuous-paper skipped-opportunity pattern that survives strategy-abstention-only filtering, market-aware discovery, aggregate chronological holdout, and three later validation blocks is frozen as a research-only prospective shadow candidate. It does not modify the active paper strategy.

**Frozen candidate:** Candidate `2f72dd8fcb0b8cef3a4eb991d472a0e9c50f550954d1b3d8a0ddd3d6fe1cfd23` studies strategy abstentions in market `MON` while volatility regime is `normal`, with SHORT as the frozen direction, a 1h forward horizon, and a 50 bps material-move analysis threshold. The authenticated source evidence artifact digest is `sha256:b91486afbd31778b075712512b81d7e94b6c2db716683fc0fe4d4954ba388ca1`.

**Touched evidence:** The discovery/validation evidence remains touched research evidence. It contained 52 discovery material outcomes with a 61.54% SHORT share and 25 later material outcomes with a 76% SHORT share. The later block shares were 75%, 75%, and 77.78%. These numbers justify freezing a hypothesis only; they do not authorize a trade.

**Prospective boundary:** The candidate is frozen at `1791291300000` ms and may score prospective decisions only from `1791312900000` ms onward, preserving the existing six-hour prospective embargo. Decisions before that boundary are never backfilled into prospective evidence.

**Scoring semantics:** Future evidence counts only post-boundary, strategy-abstained decisions that match the frozen context and 1h horizon. The scorer records raw directional markout and material-move direction share. It does not assume a fill, does not claim hypothetical PnL, and is not cost-complete.

**Review gate:** Prospective evidence becomes `ready_for_review` only after at least 30 material outcomes, at least 60% alignment with the frozen direction overall, and three chronological future blocks with at least five material outcomes each and at least 55% directional alignment in every block. A flipped or undersampled block keeps the candidate unready even when the aggregate share looks favorable.

**Review authority:** `ready_for_review` is not promotion authority. It only means the frozen hypothesis has accumulated enough clean future evidence for a later explicit research review. It cannot mutate the active paper strategy, bypass tradeability/risk gates, or enable live execution.

**Immutability:** Market, volatility regime, direction, horizon, material threshold, source lineage, selection policy, and prospective boundary are immutable for this candidate. Any retune creates a new candidate identity and a new future boundary.

**Authority:** Prospective scoring is paper research only. It cannot change entries, suppress either direction globally, relax risk/tradeability gates, authorize promotion, or enable live execution.

**LIVE TRADING: DISABLED.**


## D-036 — Cooldown relaxation contexts must be re-proven prospectively

**Date:** 2026-10-07

**Decision:** A context that appears to make the consecutive-loss cooldown too conservative may not relax the active risk veto directly. After the existing cooldown counterfactual, context-stability, and immutable selection stages choose a stable context, that exact context must be frozen once and re-evaluated on later continuous-paper evidence after the standard six-hour prospective embargo.

**Context boundary:** A frozen cooldown candidate must retain the exact relaxation window and lead-strategy context selected by the touched evidence. Additional dimensions such as direction, elapsed-cooldown bucket, or rank band remain frozen when they are part of the selected context. Direction alone can never define a cooldown relaxation.

**Economic target:** Prospective scoring uses the same settled 1h fee-adjusted mark-to-market PnL and directional-return semantics used by the context-selection research. It counts only opportunities that were actually eligible for the frozen relaxation window and match every frozen context dimension.

**Review gate:** The frozen context remains unready until it has at least 30 post-embargo settled outcomes across at least four markets, at least 60% profitable outcomes, positive total fee-adjusted PnL and mean directional return, positive leave-one-option and leave-one-market PnL, and three chronological prospective blocks with at least five rows, at least 55% profitable outcomes, and positive PnL in every block.

**Immutability:** The first frozen cooldown candidate is immutable. Later research cannot overwrite it with a newly selected context. A materially different cooldown hypothesis requires a new explicit candidate identity and a fresh prospective boundary.

**Operational isolation:** Freeze restoration, scoring, and artifact publication run only in the post-handoff research tail after the exact successor has been dispatched and durable fallback state has been published. Missing/corrupt research state fails research closed and may not delay or alter the paper trader.

**Authority:** `ready_for_review` is research review only. It does not change the one-hour cooldown, strategy logic, position sizing, risk limits, promotion state, or execution authority.

**LIVE TRADING: DISABLED.**


### D-037 — Recurring loss contexts require economic holdout validation

A repeated losing streak is not sufficient evidence to suppress a direction or strategy globally. Loss-streak research must translate any proposed avoidance rule into an entry-time context that includes `lead_strategy` plus market-state context; direction-only candidates are forbidden.

For a recurring context to become eligible for a later prospective freeze, the counterfactual filter must improve realized net PnL on a chronological holdout, span multiple markets, remain positive after removing any one trade and any one market, and stay positive across later chronological blocks. Counterfactual filter delta is defined as the negative of realized net PnL for matching executed trades: avoiding a loser helps, while avoiding a winner hurts.

This gate is research-only. It cannot change strategy, block entries, alter risk limits, promote a candidate, or grant execution authority. Any stable context still requires a separate immutable prospective freeze and genuinely future paper evidence before strategy use.


### D-038 — Stable loss contexts must be frozen and re-proven on future realized trades

A recurring loss-context candidate that survives D-037 is still touched evidence. The first deterministic stable candidate is frozen immutably, keeps its exact lead-strategy plus entry-time market context, and waits through the standard six-hour prospective embargo before any later trade can count.

Prospective scoring uses only realized continuous-paper trades opened after the embargo. For a matching trade, counterfactual filter delta is the negative of actual realized net PnL: avoiding a loser helps the candidate and avoiding a winner hurts it. Future lineage gaps fail review closed because an unresolved future trade could have matched the frozen context.

Review readiness requires at least 30 matching post-embargo trades across at least four markets, at least 60% beneficial avoidances, positive total and mean filter delta, positive leave-one-trade and leave-one-market delta, and three later chronological blocks with at least five matches, at least 55% beneficial avoidances, and positive delta in every block.

The frozen candidate is research-only. Review readiness cannot block an entry, change LONG/SHORT preference, alter risk or sizing, promote a strategy, or grant execution authority. Any actual strategy admission remains a later explicit evidence-gated step.

**LIVE TRADING: DISABLED.**


### D-039 — Durable paper evidence survives non-economic handoff-tail failures

A continuous-paper workflow's final GitHub conclusion is not, by itself, the economic validity boundary for research evidence. A completed run may remain evidence-eligible after a narrowly defined control-plane tail failure only when the paper trader completed successfully, durable state was measured and published successfully, the exact source artifact required by the consumer was published successfully, and source run/repository/attempt/artifact lineage all authenticate.

For the observed redundant fallback-successor failure, eligibility additionally requires that the fast exact successor was already queued successfully. The only permitted failed-step sets are the existing fail-closed handoff-tail step alone, or that step together with the redundant fallback-successor step under the successful-fast-successor condition. Any other failed step, missing required publication, missing artifact, incomplete trader, invalid lineage, or missing successor continuity fails closed.

This is an evidence-continuity rule only. It does not reinterpret failed trading/execution as success, does not modify strategy/risk/sizing/stops, and grants no promotion or live-order authority.


### D-040 — Loss-context learning refreshes on every clean paper handoff

Loss-context research must not depend on a runtime code upgrade to receive new evidence. After the exact successor paper worker has already been dispatched, the D-037/D-038 loss-context audit may rebuild from either of the two normal completed runtime exits: `duration_elapsed` or `upgrade_requested`.

Any other or unknown session exit remains ineligible and fails research closed. The audit still requires the persisted journal, evaluation facts, entry-time feature snapshots, and opening-rank evidence; no missing lineage is guessed or backfilled.

The post-handoff position is deliberate: research may take time or fail without delaying the next paper trader. A stable context remains research-only and still requires the immutable D-038 freeze, six-hour embargo, and genuinely later realized trades before review.

This changes evidence cadence only. It does not block entries, prefer LONG or SHORT, change risk/sizing/stops, promote a candidate, or grant execution authority.

**LIVE TRADING: DISABLED.**


### D-041 — Loss-context filters must leave a profitable fixed-schedule portfolio

D-038 review readiness proves that one frozen recurring setup remains harmful on later realized paper trades. A positive avoided-loss delta is not sufficient account-level evidence: removing bad trades can make a losing strategy less negative while the remaining portfolio still loses money.

Before a D-038 candidate may advance to capacity-reflow investigation, Cocomelon must evaluate the same post-embargo resolved future cohort on a fixed schedule. Trades matching the immutable frozen context contribute zero, while all non-matching trades retain their actual realized net PnL and net-R. The resulting filtered portfolio must have positive total net PnL and net-R, the improvement versus baseline must also be positive, and both the filtered portfolio and the improvement must remain positive after removing any one trade and any one market. The avoided-loss PnL must exactly reconcile to D-038's prospective filter delta; cohort drift or unresolved future lineage fails closed.

Passing this gate permits only later capacity-reflow research. It does not assume freed risk or correlation capacity stays idle and does not model replacement or recursive portfolio effects. Those effects remain required before any strategy-admission decision.

Direction-level counts are diagnostic only and direction-only filtering remains forbidden. This gate cannot alter paper entries, side preference, risk, sizing, stops, promotion state, or execution authority.

**LIVE TRADING: DISABLED.**


### D-042 — Loss-context capacity reflow must be causally attributable

D-041 fixed-schedule profitability is a prerequisite for studying portfolio reflow; it is not permission to assume that a skipped bad-context trade turns directly into account profit.

Once D-041 is ready, reflow research may inspect later paper opportunities that the baseline rejected specifically for aggregate-risk or correlation-bucket capacity. A release is attributable to the frozen loss-context candidate only when removing one position from the captured decision-time risk request makes capacity available, that exact position was opened after the D-038 prospective boundary, its immutable entry context matches the frozen candidate, and the later replacement opportunity does not itself match the same frozen bad context.

Missing holder lineage, unresolved holder trades, or missing entry-context evidence fails the reflow evidence closed. Positions opened before the prospective boundary cannot be credited to the candidate.

This stage proves only causal single-position capacity release. It does not claim a replacement entry filled, does not model replacement exits or PnL, and does not model recursive replacements. Those are separate later evidence stages.

No active strategy, side preference, risk limit, sizing, stop, promotion state, or execution behavior changes.

**LIVE TRADING: DISABLED.**


### D-043 — Freed loss-context capacity must be executable before replacement credit

D-042 proves that removing a frozen bad-context holder would causally free capacity for a later opportunity. That is still not enough to credit the capacity as economically usable. Before any replacement entry can be modeled, the exact holder release must be replayed against captured decision-time execution evidence.

Only causal D-042 release options are eligible. The holder-release replay must use the captured paper execution configuration, reduce-only planner, configured latency, captured L2 book, fees, instrument metadata, and exact opening-plan lineage. A full close is required before the option can advance to replacement-entry investigation; partial fills, no fills, planning rejections, unbound execution configuration, missing captured books, or lineage conflicts cannot be treated as freed capacity.

Each opportunity/holder release path is evaluated independently. Repeated hypothetical releases of the same holder at different opportunity times are not collapsed into one terminal value because their captured books may differ.

This stage records execution feasibility only. It does not place or modify a paper position, does not model the replacement entry, replacement exit, replacement PnL, or recursive reflow, and grants no strategy, risk, promotion, or execution authority.

**LIVE TRADING: DISABLED.**


### D-044 — Capacity-release capture must match the causal reflow universe

The decision-time holder-release book capture must use the same exact single-position capacity test as D-042. A holder is registered only when removing that exact open risk position from the captured RiskRequest makes positive capacity available for the rejected opportunity.

This capture applies to both `aggregate_risk_exhausted` and `correlation_bucket_exhausted`. Correlation-bucket membership by itself is not sufficient evidence that a holder caused the rejection, and aggregate-risk releases must not remain invisible merely because the holder is in a different bucket.

The rule is prospective. Existing historical release-book evidence is not guessed or backfilled, and legacy captures remain identifiable by their original timestamps/configuration. Missing exact release books remain missing evidence rather than synthetic fills.

This changes research evidence coverage only. It does not alter active risk limits, release positions, entry priority, strategy direction, sizing, stops, promotion state, or execution authority.

**LIVE TRADING: DISABLED.**


### D-045 — Replacement entries require exact post-release account replay

A D-043 full holder close does not itself prove that the newly available opportunity becomes a real replacement trade. Each exact full-close release option must independently rerun the captured replacement opportunity through the normal risk engine, opening planner, and IOC simulator.

The counterfactual account must first remove the holder's decision-time contribution and then apply that option's exact D-043 full-close terminal contribution. This terminal contribution is bound per opportunity/holder release option, not merely per opening plan, because the same holder can have different executable exit economics at different opportunity times.

The replacement replay uses the captured opening opportunity, ordinary paper execution configuration, execution latency, L2 book, instrument metadata, sizing/risk limits, and fees. Risk rejection, planning rejection, no fill, partial fill, and full fill remain distinct evidence states.

A full or partial replacement entry may advance only to later replacement-exit investigation. Entry fill evidence does not claim a replacement exit, replacement realized PnL, recursive reflow, strategy improvement, or promotion readiness.

This stage is research-only and cannot alter active positions, strategy direction, risk limits, sizing, stops, promotion state, or execution authority.

**LIVE TRADING: DISABLED.**


### D-046 — Replacement PnL stays fixed-horizon and funding-complete

A D-045 replacement entry fill may be evaluated at the already captured fixed exit horizons only. Each horizon remains a separate economic question; this stage may not select the best horizon, average horizons together, or present cross-horizon PnL as one strategy result.

For every filled replacement option, exit execution must use the captured horizon-specific L2 evidence, ordinary reduce-only planner, configured latency, IOC simulator, and fees. Exact realized PnL is available only when the replacement position fully closes and every funding boundary between entry and exit has exact captured funding evidence. A position with no funding boundary has exact zero funding for that horizon.

A horizon is complete only when every replacement option has exact realized PnL at that horizon. Portfolio-counterfactual investigation may begin only when every frozen horizon is complete. Positive PnL at one horizon does not authorize selecting it, changing exits, or claiming strategy improvement.

This stage does not build the portfolio counterfactual, aggregate horizons, choose an exit schedule, mutate strategy/risk/positions, grant promotion authority, or enable execution.

**LIVE TRADING: DISABLED.**


### D-047 — Independent replacement paths must compose before portfolio replay

D-046 evaluates each replacement option independently at every frozen horizon. Those independent paths may not be summed and presented as portfolio profit. Before a chronological portfolio counterfactual can begin, every frozen horizon must have complete exact replacement-exit PnL and the option set must be structurally composable.

Structural composition fails closed when one opening opportunity has multiple independently fillable holder-release paths, the same released holder is reused to justify multiple replacement opportunities, or replacement lifetimes overlap at the same fixed horizon. These cases require an explicit chronological account-state decision rather than favorable path selection or double counting.

The composition audit may report a first-order diagnostic equal to the D-041 filtered fixed-schedule PnL plus exact D-046 replacement PnL. That number is not a portfolio counterfactual because prior replacement PnL, account equity, daily loss, rolling drawdown, open positions, and later risk decisions have not yet been replayed chronologically.

A horizon may advance only to chronological portfolio replay when it is complete and structurally composable. Horizons remain economically separate; no best horizon is selected or averaged.

This stage is research-only and cannot change strategy, LONG/SHORT preference, risk limits, sizing, positions, stops, promotion state, or execution authority.

**LIVE TRADING: DISABLED.**


### D-048 — Portfolio shadow proof requires a fresh immutable freeze

D-047 only proves that the independently measured replacement paths are structurally capable of being composed. It does not authorize those touched paths to become a portfolio claim. Before any full loss-context portfolio shadow can begin, the complete shadow specification must be frozen immutably and evaluated only on genuinely later mainnet paper evidence.

The freeze binds the original loss-context candidate, exact context dimensions/values, the complete ordered set of fixed exit horizons, source composition digest, source evidence boundary, and producer run identity. It preserves every D-046 horizon. No horizon may be selected, averaged, dropped, or retuned from the touched composition evidence.

The portfolio shadow receives the standard six-hour prospective embargo after the freeze. Evidence before that boundary is ineligible for shadow-account proof. Any materially different context or horizon set requires a new candidate identity and a new future boundary.

This freeze grants no strategy, risk, sizing, position, stop, promotion, or execution authority. The active continuous-paper strategy is unchanged. The next stage may build a separate prospective shadow account that evolves its own equity, cooldown, drawdown, capacity, entries, and exits from the future stream.

**LIVE TRADING: DISABLED.**


### D-049 — Portfolio shadow changes admission only at the opening boundary

The prospective loss-context portfolio shadow must not rewrite strategy decisions, disable a direction, or alter position-management signals. Its only candidate-specific difference from the paired baseline shadow is an opening-admission veto applied immediately before the normal risk request and paper execution path.

The veto matches every frozen D-048 context dimension exactly using information available by the opening attempt. Supported dimensions are lead strategy, trend regime, volatility regime, 15m/1h return sign, direction when it is part of the frozen context, and coarse rank band. Rank-band matching uses the latest coarse rank known no later than the opening attempt, preserving the same entry-time semantics used by historical opening-rank evidence.

Before the D-048 prospective boundary, both shadow lanes refuse new exposure while still being allowed to warm market/feature state. After the boundary, the baseline shadow admits every ordinary directional setup to the unchanged risk/execution path; the candidate shadow blocks only the exact frozen context. Same-side setups with different strategy/regime context remain eligible.

A blocked shadow entry never creates a risk decision, execution attempt, fee, position, or capacity claim. Existing/open shadow positions continue to receive the ordinary unmodified strategy decisions for position management, so the filter cannot silently alter exits.

The generic opening-admission hook defaults to absent and therefore does not change the active continuous-paper trader. This stage only prepares the reusable mechanism for the isolated future A/B shadow accounts.

**LIVE TRADING: DISABLED.**


### D-050 — Prospective portfolio proof uses paired isolated accounts

The D-048 loss-context portfolio hypothesis must be evaluated with two independent paper accounts consuming the same chronological mainnet evidence stream. Both lanes use the same frozen replay configuration, strategy logic, risk engine, sizing, execution model, position-management rules, fees, funding, and market data.

Before the D-048 prospective boundary, both lanes refuse new exposure. After the boundary, the baseline lane admits every ordinary directional setup into the normal opening path while the candidate lane applies only the exact D-049 frozen-context opening veto. The candidate must never suppress a whole direction or rewrite strategy decisions.

Each lane owns independent cash, equity, open positions, daily realized PnL, rolling seven-day peak, drawdown, consecutive-loss state, risk capacity, fills, fees, funding, and closed-trade lifecycle. Account-level differences are therefore allowed to compound naturally through later risk/cooldown/capacity decisions instead of being approximated by summing independent trade paths.

The paired engine records candidate-minus-baseline equity, total account PnL, realized net PnL, drawdown, opening/risk activity, and admission counts. Matching-context avoidance is useful only if the isolated candidate account eventually proves superior on genuinely future evidence; the existence of a positive delta on one short run grants no strategy or promotion authority.

This paired shadow is research-only and remains isolated from the active continuous-paper account. It cannot alter the active strategy, LONG/SHORT preference, risk limits, sizing, stops, positions, cooldown, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### D-051 — Paired shadow handoffs may not discard staged openings

The prospective paired portfolio shadow may not publish or restore a handoff checkpoint while either lane has a directional opening already staged but not yet resolved against its post-latency book.

A staged opening is economically material: dropping it at a worker boundary could change fills, risk capacity, cooldown state, drawdown, later entries, and account PnL. Until pending-opening state itself is durably serializable, the safe rule is to expose both lanes' pending markets and declare the shadow handoff safe only when both sets are empty.

This constraint applies only to the research shadow and may never delay, block, or alter the active continuous-paper trader. If a worker must hand off while the shadow is unsafe, shadow continuity fails closed rather than inventing a clean A/B continuation.

**LIVE TRADING: DISABLED.**


### D-052 — Paired shadow restart state must bind both account and lifecycle lineage

A D-050 paired portfolio shadow may continue across rolling paper workers only from a D-051 handoff-safe checkpoint that binds the immutable portfolio-shadow candidate, exact replay-configuration digest, selected market set, each lane's exact persisted paper-account state ID, open lifecycle lineage, recorded mark path, exit-plan history, funding history, known data gaps, cumulative admission/activity counters, and maximum observed drawdown. The checkpoint itself carries a canonical SHA-256 content digest; edited or partial receipts fail closed.

The independent baseline/candidate SQLite stores remain the economic source of truth. The JSON shadow checkpoint is a lineage/restoration receipt, not a replacement account ledger. Both current account snapshots are explicitly materialized at checkpoint time, including a lane that has intentionally taken no trade. On restore, the account market set must exactly match the lifecycle checkpoint market set and every opening/exit plan referenced by an open lifecycle must exist in that lane's own execution store. An execution store without its checkpoint, a checkpoint without both stores, or any lineage mismatch fails the research shadow closed.

Decision-engine market history is not guessed from the checkpoint. After restore, new directional decisions remain disabled until the caller has supplied fresh startup/warmup evidence and explicitly marks restore warmup complete. Existing restored positions may then continue through the ordinary lifecycle engine.

Candidate identity changes, unsafe staged-opening checkpoints, account-state mismatches, corrupt lifecycle history, or authority-bearing state are all restart failures. They may never reset or alter the active continuous-paper account.

**LIVE TRADING: DISABLED.**


### D-053 — Paired shadow runtime must be isolated from active paper latency

The D-050 paired loss-context portfolio shadow may consume the active continuous-paper evidence stream only through a bounded, ordered side channel that cannot block or back-pressure the real paper trader. Active paper processing always completes first. The shadow receives a best-effort non-blocking enqueue afterward; paired replay, SQLite accounting, risk evaluation, execution simulation, checkpointing, and summary work run on a dedicated worker thread rather than the market-data event loop.

Queue overflow, shadow replay failure, corrupt durable state, candidate mismatch, unsafe staged openings, checkpoint timeout, or market-coverage conflict disables/fails the research shadow closed. None of those failures may change or delay active strategy decisions, risk checks, paper positions, exits, account state, or worker handoff.

Rank snapshots, restore-warmup completion, and shortlist reconciliation are serialized through the same ordered actor. A restored shadow uses its persisted selected-market lineage first. It may reconcile to the active shortlist only when doing so does not drop coverage for an open baseline/candidate shadow position; otherwise the shadow fails closed rather than silently stranding a position.

The immutable D-048 portfolio-shadow candidate is restored before the trader starts when trusted evidence is available. The paired checkpoint is written only after the active paper runtime has stopped and its own checkpoint has been persisted. The paired state then rides inside the ordinary authenticated continuous-paper resume/durable state, while a separate research artifact is published only after successor dispatch so research publication cannot delay continuity.

This integration remains research/shadow only. It cannot modify LONG/SHORT preference, active entry admission, risk limits, sizing, stops, positions, cooldowns, promotion state, or live-order authority.

**LIVE TRADING: DISABLED.**


### D-054 — Paired shadow review requires profitable, diversified future proof

The D-050/D-053 paired portfolio shadow may become eligible for research review only from its immutable, genuinely prospective A/B account history. A single latest snapshot, aggregate directional PnL, touched evidence, or a candidate that merely loses less than baseline is insufficient.

Every safe handoff appends a canonical hash-chained review checkpoint and binds the latest ledger row count/digest into the durable paired-shadow checkpoint. Historical rows cannot be rewritten without breaking the chain or restart receipt. The first eligible ledger row is an anchor only: duration, trade-count growth, matching-context growth, market diversity, and chronological block deltas must come after that anchor. Legacy matching-context counts that predate per-market attribution remain visible but are explicitly excluded from market-diversity readiness.

The minimum review floor is 72 hours after the D-048 prospective boundary, at least nine authenticated handoff checkpoints, at least 30 newly attributed matching-context blocks across at least four markets, no single blocked market above 50% of attributed matches, and at least 30 closed trades in each paired lane.

Economically, the candidate account itself must have positive total account PnL and positive realized net PnL. It must also beat baseline on both total account PnL and realized net PnL while having maximum drawdown no worse than baseline. This prevents a "less bad but still losing" filter from qualifying.

The eligible checkpoint history is divided into three chronological later blocks. Every block must contain at least five newly attributed matching-context blocks across at least two markets, and candidate-minus-baseline total-account-PnL and realized-net-PnL improvement must both be positive within every block. This blocks one short lucky interval from carrying the full claim.

`ready_for_review` remains research review only. It does not activate the filter, suppress LONG or SHORT globally, alter strategy/risk/sizing/stops/cooldowns/positions, grant promotion authority, or enable live orders. If the gate is not ready, Cocomelon keeps collecting future evidence without relaxing thresholds.

**LIVE TRADING: DISABLED.**


## D-055 — D-039 evidence eligibility applies to all durable paper consumers

**Date:** 2026-10-07

**Decision:** Research consumers that depend on authenticated continuous-paper artifacts must apply the D-039 evidence-eligibility contract consistently. A paper run is eligible when it completed successfully, or when the trader, durable-state measurement, and durable-state upload all succeeded and the run failed only in the narrowly authenticated post-trader handoff tail already allowed by D-039.

**Immediate repair:** Continuous Paper Exact Path Export and the Prospective Two-Strike Stop Filter Ledger may consume those narrowly eligible handoff-tail-failed runs when the exact expected artifact for the same run/attempt exists. They may not consume arbitrary failed, cancelled, timed-out, corrupted, or pre-state runs.

**Fallback consequence:** Automatic source discovery treats workflow completion events only as wake signals. It sorts completed main-branch paper runs newest-first, verifies D-039 eligibility per run, then requires the exact state or compact artifact before selection. This prevents a late-completing older worker from moving an append-only evidence consumer backward. A non-success workflow wake is therefore not evidence loss by itself.

**Manual consequence:** Exact manual dispatch remains strict. If a manually supplied paper run is not D-039 evidence-eligible or lacks its exact artifact, the consumer fails closed instead of silently switching sources.

**Authority:** This restores evidence continuity only. It does not change strategy, risk, sizing, entries, exits, readiness thresholds, promotion status, paper positions, or live-order authority.

**LIVE TRADING: DISABLED.**


## D-056 — Late exact paper dispatches are idempotent stale replays

**Date:** 2026-10-07

**Decision:** An authenticated exact paper-source dispatch that arrives after an evidence ledger has already accepted a newer paper run must not roll the ledger backward and must not fail the evidence campaign merely because GitHub completed or dispatched workers out of order. After the candidate/state identity is re-verified, a strictly older paper run/attempt is treated as an idempotent stale replay and the already-validated newer ledger is returned unchanged.

**Initial scope:** The Prospective Range-Compression Entry Evidence ledger and Prospective Momentum-Pullback Fast-Markout ledger now apply this rule because both receive exact dispatches from continuous-paper workers and both were observed receiving older workers after newer evidence had already been recorded.

**Integrity boundary:** Stale replay handling does not append the old source to source history, does not replace rows, does not recompute economics from the old source, and does not weaken duplicate-source drift checks or forward append-only checks. A different frozen candidate/state still fails closed. Equal or newer source identities continue through the ordinary validation path.

**Observability:** Workflow status must show both the dispatched source identity and the ledger's latest accepted source identity, and explicitly state when the dispatched source was ignored as stale.

**Authority:** Evidence-ordering reliability only. No strategy, risk, sizing, entry, exit, readiness, promotion, paper execution, or live-order behavior changes.

**LIVE TRADING: DISABLED.**
