# Frozen SHORT breakout: isolated dual-account paper replay

**Research infrastructure; no sourced forward result yet.** This module is deliberately separate from both the live original continuous paper account and the negative frozen v5 paired-shadow account.

`ShortRankIndependentPairedPaperReplay` runs two isolated `PaperExecutionAdapter` and `BaselineReplayPipeline` instances on the **same exact ordered `ReplayRecord`** inputs. Each lane persists its own SQLite execution store and evaluation facts. The only intended difference is the frozen causal candidate admission filter for SHORT breakout opportunities ranked beyond 3 (see `FORWARD_SHORT_RANK_PAIRED_ADMISSION.md`). Both lanes use the same starting capital, config, strategy logic, position exits, risk engine, mainnet book simulation, fees and funding mechanics when those corresponding records are provided.

A locally computed source-stream hash identifies which rows were delivered to the two lanes, and a supplied `ReplayManifest` labels their proposed origin. The harness rejects order regressions, record duplication (identical sort key), outside-manifest timestamps, non-microstructure source types and attempts to reuse an existing account directory. If either simulator fails, **neither** economic report may publish. The output includes account marked and realized net PnL, filled entries, closed net sums, residual cash, funding, fees, positions, margin, and observed drawdown separately, plus challenger-minus-baseline absolute after-cost cash. These are actual simulated account mechanics, **not** journal skip arithmetic.

## Important unresolved proof obligations

The harness **does not** authenticate the manifest's segment files, signature or provenance, independently attest that external rank-witness callbacks reflect original first-seen observations, supply or guarantee complete future market streams, persist decision engine state for handoff, or certify that all open positions have matured. Until separately addressed, `source_manifest_independently_authenticated`, `rank_witness_source_independently_authenticated`, `checkpoint_handoff_continuity_certified`, `complete_forward_observation_maturity_certified`, `full_account_trial`, `ready_for_review`, `execution_authority`, and `promotion_authority` remain **false**.

Regression tests use unmistakably synthetic fixtures **only for deterministic unit behavior**: one SHORT breakout losing exit actually executed in baseline but rejected in challenger; both accounts execute the same loser when the opening rank is unwitnessed; source replay duplicates and attempts to reuse accounts fail closed. These fixtures are not purported observations from Hyperliquid, not an economic backtest, and not evidence for promotion.

Next integration must verify the genuine archived forward source segments and their chronological original first-seen decision/rank receipts, provide a read-only runner consuming **authenticated future mainnet** records, add explicit state-preserving handoff and open exposure/censoring proof, and perform noncherry-picked fixed-time risk-matched account comparison. No frozen v5 history or original paper orders may be reset.

**Paper only. Original strategy, all stops, daily/weekly risk limits, and live trading disabled.**
