# Frozen SHORT breakout rank: independent paired-paper admission boundary

**2026-10-11, research only.** The already-frozen `prospective-short-breakout-only-top3-v1` study currently computes hypothetical zero-replacement skipped cash. It is **not** a simulated capital-constrained account, and none of its historical/delayed evidence can justify promotion.

## What the new boundary supplies

`ProspectiveShortBreakoutPairedEntryFilter` is a pure *opening admission* policy for a future **separate baseline and challenger paper simulation**. Both instances share the exact `ProspectiveShortBreakoutRankState`, decision, feature, timestamp, and rank-witness provider. Both exclude pre-start attempts. Only the candidate can reject eligible SHORT + breakout leads ranked beyond #3. Rank 1–3 and all other confirmed strategies/directions remain eligible for the ordinary downstream risk engine and simulated fills.

A rank can justify rejection only when its observation is strictly **before the strategy decision**, no more than 300,000 ms old, and its source context matches the actual decision/feature lineage. Future-stamped rank evidence and contradictory decision lineage **raise an error**. Missing, stale, same-millisecond, or unverifiable lead/rank inputs retain openings in **both** lanes and mark a source-incompleteness counter; these must not count as proven avoided losses. This deliberately errs against the candidate and can yield fewer hypothetical skips than retrospective journal scoring. The provider must supply genuinely observed ranks, not ranks reconstructed after a trade outcome.

The new admission code is not connected to the original continuous paper trader or frozen v5 paired account. It has no account stores, replay source, fee/funding ledger, signed snapshots, true matched exposure, or review authority. Its own summary explicitly records `actual_paired_accounts_running=false`, `full_account_trial=false`, `ready_for_review=false`, and no execution/promotion authority.

## Required next construction stage — not yet done

Build a separately named and frozen paired replay with two independently persisted `PaperExecutionAdapter` accounts, identical initial cash, identical actual mainnet `ReplayRecord` observations, normal strategy/risk/position-management/IOC rules, actual simulated fills, friction and funding. Use this filter **only** in the challenger and the pass-through boundary in baseline. Preserve the original v5 accounts and trial untouched.

Before any claim of profitability, independently verify exact record-source identity and timeline, no future-derived rank, both risk budgets/position exposure, actual fill and fee/funding effects, realized and marked account PnL, open positions and exits, market-specific gaps, cumulative and peak drawdowns, and loss/stability in immutable forward windows. Missing source or handoff state must fail closed, never become zero-cost fills. Never use the historical short-rank skip-only report as the independent account result.

No original paper order, live order, risk limit, frozen hypothesis, historical evidence, or promotion gate has changed.
