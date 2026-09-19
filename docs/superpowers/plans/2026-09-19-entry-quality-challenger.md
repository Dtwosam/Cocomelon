# R2 Entry-Quality Profitability Challenger Plan

**Status:** active  
**Created:** 2026-09-19  
**Updated:** 2026-09-19  
**Supersedes for active execution:** `2026-09-14-research-natural-rollout-validation.md`  
**Scope:** touched research and failed-baseline retirement only; no live trading, leverage increase, or risk-limit relaxation.

## Goal

Use the deliberately revealed V4 failure sample as touched development evidence to test one narrow profitability hypothesis on new authenticated mainnet research captures: materially improve trade selection by allowing only moderate-score, trend-led SHORT entries while preserving the existing paper execution and risk model.

The objective is not to make an early positive sample look good. The objective is to reject this hypothesis quickly if it lacks positive net expectancy after modeled costs, or freeze it for future clean validation only if it satisfies the locked D-023 research gates.

## Starting evidence

- The revealed authenticated 100-trade V4 sample is TOUCHED / DEVELOPMENT-ONLY.
- Approximate revealed economics: `-$629.91` net PnL, `-$537.62` gross PnL, mean net R `-0.298R`, profit factor `0.44`, realized closed-trade max drawdown `7.80%`, 24 winners / 76 losers.
- Gross expectancy was negative before fees/funding, so cost tuning is not the primary repair.
- Longs materially underperformed shorts.
- Very high strategy-score trades, particularly 90–95, materially underperformed moderate-score trades in the touched sample.
- The touched subgroup `trend + SHORT + score 75..80` motivated R2, but that subgroup is selection-biased and is **not** evidence of forward edge.
- Existing `research-r1-exit-15m-v1` remains negative, so simply shortening the maximum holding horizon is not the primary hypothesis.

## R2 immutable hypothesis

Candidate ID: `research-r2-entry-quality-v1`.

Only one strategy behavior changes:

- preserve existing five-family signal generation and deterministic combination;
- preserve pre-existing `NO_TRADE`;
- permit a directional decision only when:
  - lead strategy is `trend`;
  - direction is `SHORT`;
  - final strategy score is between `75` and `80`, inclusive;
- otherwise convert the directional decision to `NO_TRADE` with reason `entry_quality_challenger_filter`.

Execution and risk remain unchanged from `scheduled-research-root`:

- starting cash: `10000`;
- maximum position age: `1,200,000` ms;
- paper only;
- 0.25% planned risk per trade and all existing aggregate/daily/weekly/correlation/liquidity guards unchanged.

## Task 1: Retire the failed V4 acquisition lane

- [x] Remove the future economic cron from the pinned V4 campaign.
- [x] Keep the workflow/runtime pinning intact as an audit surface.
- [x] Keep manual dispatch fail-closed so retirement cannot become an ad-hoc evidence backfill path.
- [x] Report scheduler state as retired rather than stale.
- [ ] Verify the merged production dashboard reports the retirement state.

Do not delete historical artifacts or mutate the touched corpus.

## Task 2: Build R2 behind tests

- [x] Add RED tests for the selective entry rule.
- [x] Add immutable candidate-code-revision registration support.
- [x] Generalize rollout verification beyond the legacy fixed 20m/15m pair while preserving legacy horizon assertions for those identities.
- [x] Remove workflow logic that silently skips verifier enforcement for a new challenger identity.
- [x] Add the R2 candidate specification using the root execution horizon.
- [x] Keep risk and live-order behavior unchanged.
- [ ] Obtain clean GREEN compile, Ruff, mypy, full pytest, and research smoke on the exact branch head.

## Task 3: Register R2 immutably

- [x] Make the trusted registration workflow run automatically when the R2 spec first reaches `main`.
- [x] Pin R2 `code_revision` to that registration push's exact `GITHUB_SHA`.
- [x] Extend registry consumers to trust successful registration `push` provenance only for the registration workflow, without trusting arbitrary pushes as research authority.
- [ ] Verify the post-merge registration run succeeds and publishes `research-authoritative-registry`.
- [ ] Verify the research dashboard renders R2 from the authenticated registry.

## Task 4: Forward-test naturally

- [ ] Do not manually dispatch an economic research cohort to create a favorable sample.
- [ ] Let the existing safe-gap dispatcher launch at most one successful research cohort per UTC day.
- [ ] Require actual V4 authority completeness/disjointness for all inherited historical protected intervals; nominal cron assumptions are insufficient.
- [ ] Require the pre-publication rollout verifier and independent final verifier on every root+R2 cohort.
- [ ] Count only authenticated successful checkpoints; failed/contaminated/running/evaluating attempts remain NOT COUNTED.
- [ ] Keep economics TOUCHED / NON-PROMOTIONAL.

## Task 5: Apply the locked research decision rules

At at least 20 R2 closed research trades:

- reject R2 for futility if `P(mu > 0) < 0.05`;
- otherwise continue without declaring success.

Do not mark `RESEARCH_PROMISING` before all are true:

- at least 40 R2 closed research trades;
- at least 7 distinct closed-trade UTC days;
- `P(mu > 0) >= 0.80`;
- modeled fees/funding/slippage complete;
- no integrity, contamination, or hard-risk issue.

If R2 fails, use its forward failure modes to define the next single-variable challenger. If R2 becomes legitimately promising, freeze it and follow lineage/embargo rules before starting any new untouched validation sample.

## Completion condition

This plan completes only when R2 reaches a terminal research decision under D-023: either an evidence-backed futility rejection or a legitimate `RESEARCH_PROMISING` state that authorizes freezing and planning a new clean validation period.

Completion does not authorize live trading. Phase 10 and live orders remain blocked until a future untouched candidate satisfies every locked promotion gate and the user explicitly authorizes live capital.
