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

## D-024 — Retire the revealed V4 baseline and move profitability work to R2 research

**Decision:** The user explicitly authorized revealing the active V4 baseline economics before the original 30-day one-shot finalization. That reveal intentionally ends the performance-blind status of the current V4 corpus. The V4 baseline is retired as **TOUCHED / DEVELOPMENT-ONLY** evidence and may not be represented as untouched OOS, one-shot promotion evidence, or a basis for live activation.

**Supersession boundary:** This decision supersedes D-023's V4 non-reveal requirement only for the already-revealed V4 baseline lineage. D-023's separation, provenance, contamination, research-futility, promising-candidate, embargo, and future clean-validation rules remain in force. Any future promotion candidate must earn a new untouched validation sample after its specification is frozen.

**Observed failure evidence:** The authenticated 100-closed-trade V4 corpus snapshot showed approximately `-$629.91` net PnL, `-$537.62` gross realized PnL, `-29.78R` total net R, `-0.298R` mean net R per trade, 24 winners / 76 losers, profit factor approximately `0.44`, and realized closed-trade maximum drawdown approximately `7.80%`. Costs were not the root cause because gross PnL was already materially negative.

**Operational consequence:** Stop future scheduled V4 economic acquisition for `v4-baseline-4h-thesis-expiry`. Do not cancel, retry, extend, backfill, or performance-condition historical V4 runs. Preserve the existing V4 corpus and workflow/runtime pinning for audit and touched research provenance. Live orders remain disabled.

**First replacement hypothesis:** Register `research-r2-entry-quality-v1` as a touched, non-promotional challenger pinned to its own immutable code revision while inheriting the root's 20-minute paper execution configuration and risk configuration. The first R2 hypothesis changes only entry selectivity: directional entries are permitted only for trend-led SHORT decisions with final strategy score from 75 through 80 inclusive; all other directional decisions become deterministic `NO_TRADE`. This hypothesis was motivated by touched subgroup analysis and is not an edge claim.

**Why isolate one change:** The existing 15-minute exit challenger is negative, and the failed V4 sample shows negative gross expectancy. R2 therefore tests trade selection before adding a separate profit-protection hypothesis. Combining entry filtering, stop changes, and exit changes at once would obscure causality and increase overfitting risk.

**Forward-research consequence:** R2 economics may be evaluated only through authenticated research checkpoints on new eligible captures. The D-023 futility rule still applies at 20 closed research trades. `RESEARCH_PROMISING` still requires at least 40 closed research trades, at least 7 distinct closed-trade UTC days, `P(mu > 0) >= 0.80`, complete modeled costs, and no integrity/contamination/hard-risk issue. Positive touched research never promotes directly.

**Promotion consequence:** If R2 or a later challenger becomes legitimately promising, freeze a new immutable candidate and start a new clean untouched validation period only after inherited touched-period handling and the documented embargo. Phase 10 and live trading remain blocked until the full locked promotion gates pass and the user explicitly authorizes live capital.

