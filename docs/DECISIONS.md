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


## D-028 — Pre-cutover HYPE capture transport supersedes the unreliable scheduler shape

**Decision:** D-027's economic candidate, validation window, evidence semantics, frozen observer revision, stale-anchor limit, paper-only mode, Hyperliquid endpoints, state identity, costs, occupancy rule, and qualification thresholds remain unchanged. Before any clean observation exists, the capture transport may perform one audited supersession from the original near-top-of-hour scheduler shape to an off-peak pre-warmed scheduler shape.

**Evidence:** On 2026-09-22, before the prospective window opened, repository Actions history showed sparse delivery of the frozen observer despite the declared `:03/:08/:13` attempts, including run `35721665228` being created at 11:28 UTC and not starting until 13:43 UTC. Successful observer runs were separated by hours rather than the declared redundant attempts. GitHub documents that scheduled workflows can be delayed during high load, especially around the start of the hour, and queued scheduled jobs may be dropped. This is capture-transport evidence, not economic evidence from the candidate.

**Replacement transport:** The workflow schedules one off-peak pre-warm at minute 47, keeps the runner alive until the protected minute 03 attempt, allows an already-delayed start to proceed only while the same 15-minute freshness ceiling is still satisfiable, and otherwise fails closed. The job timeout becomes 30 minutes solely to cover pre-warm sleep plus the unchanged observer. The frozen observer source remains `0131fccdb09a2b9ba959dd5785ea213a6297f719`.

**Supersession invariant:** The old control plane may be replaced only before 2026-09-23 00:00:00 UTC, only when the restored campaign contains zero observations and zero outcomes, and only when the old attestation exactly matches the known D-027 control plane. The workflow first writes an immutable `control-plane-supersession.json` receipt binding old and new control-plane IDs, the zero-evidence state, the validation boundary, and the reason code, then atomically replaces `control-plane.json`. Any unknown control plane, missing/tampered supersession receipt, non-empty evidence, or post-cutover attempt fails closed.

**Lineage consequence:** State-readiness accepts the legacy control plane only for empty artifacts audited before cutover. Append-only lineage permits exactly the attested legacy-to-replacement transition and no other control-plane drift. All later artifacts must carry the replacement control plane and immutable supersession receipt.

**Interpretation:** This is a reliability repair discovered before the first clean sample, not a candidate retune. D-027 remains authoritative for economics and validation. After cutover, the replacement transport is frozen and any material capture change requires a new campaign.
