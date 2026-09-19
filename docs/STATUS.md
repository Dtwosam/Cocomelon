# Cocomelon Project Status

**Last updated:** 2026-09-19  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Last verified main before this change:** `10160247a32c91d31bb3f6123b424a80cb5b2345`  
**Active plan:** `docs/superpowers/plans/2026-09-19-entry-quality-challenger.md`  
**Live trading:** **DISABLED**  
**Phase 10:** **BLOCKED**

## Current strategy state

The former V4 thesis-expiry baseline is **RETIRED / TOUCHED / DEVELOPMENT-ONLY** under D-024.

The user explicitly authorized revealing its economics before the original 30-day one-shot finalization. That action intentionally ended the corpus's performance-blind status. The existing V4 corpus remains valuable for audit and failure analysis, but it can no longer establish untouched OOS edge or support promotion.

The authenticated 100-closed-trade snapshot that was inspected showed approximately:

- net PnL: **-$629.91**;
- gross realized PnL: **-$537.62**;
- total net R: **-29.78R**;
- mean net R/trade: **-0.298R**;
- winners / losers: **24 / 76**;
- profit factor: **0.44**;
- realized closed-trade maximum drawdown: **7.80%**.

Gross PnL was already materially negative before fees and funding, so the failure is primarily strategy expectancy rather than transaction-cost drag.

No live order was enabled, and no live promotion gate has been relaxed.

## Retired V4 corpus

Latest trusted Evidence Dashboard snapshot observed on **2026-09-19** before retirement:

- **63 accepted V4 cohorts**;
- **112 closed paper trades**;
- **20 closed-trade UTC days**;
- **6,620 strategy decisions**;
- latest V4 corpus artifact: `10577658286`;
- latest observed V4 campaign `35426988521` finished failure;
- curator `35432351952` completed successfully and rejected that failed source as `capture_step_failed`.

The negative economic analysis above was performed on the authenticated 100-trade snapshot, not silently extrapolated to the later 112-trade corpus.

Future scheduled economic acquisition for this failed V4 candidate is being disabled. The pinned campaign code remains intact as an audit surface, and manual dispatch remains fail-closed. Historical V4 acquisition intervals, corpus provenance, and authority synchronization remain available to protect research integrity.

## Research lane

Research remains **TOUCHED / NON-PROMOTIONAL**.

D-023 still governs research thresholds and future clean validation. D-024 supersedes D-023's V4 non-reveal boundary only for the already-revealed failed V4 baseline. The revealed V4 sample may now be used as touched development evidence, but never as untouched promotion evidence.

Latest trusted Research Dashboard snapshot observed on **2026-09-19**:

### `scheduled-research-root`

- state: `researching`;
- **11 authenticated checkpoints**;
- **10 closed research trades**;
- **6 long / 4 short**;
- **7 closed-trade days**;
- touched net PnL: approximately **-$37.24**;
- mean net R: approximately **-0.149R**.

### `research-r1-exit-15m-v1`

- state: `researching`;
- **6 authenticated checkpoints**;
- **6 closed research trades**;
- **4 long / 2 short**;
- **4 closed-trade days**;
- touched net PnL: approximately **-$36.91**;
- mean net R: approximately **-0.246R**.

The existing 15-minute exit challenger therefore does not currently support the hypothesis that simply shortening the maximum holding horizon repairs the edge.

## R2 entry-quality challenger

The active build is `research-r2-entry-quality-v1`.

R2 isolates one touched hypothesis:

- preserve the current five-family signal generation and deterministic combination;
- preserve existing `NO_TRADE`;
- permit a directional entry only when the lead strategy is `trend`, direction is `SHORT`, and final score is **75 through 80 inclusive**;
- convert every other directional decision to deterministic `NO_TRADE` with reason `entry_quality_challenger_filter`.

Why this hypothesis exists:

- longs were materially worse than shorts in the revealed failure sample;
- very high strategy scores, especially 90–95, were materially worse than moderate scores;
- the touched `trend + SHORT + score 75..80` subgroup was positive in the development sample, but that subgroup is selection-biased and is **not** a forward edge claim.

R2 keeps the root execution/risk model unchanged:

- starting cash `10000`;
- maximum position age `1,200,000` ms;
- paper only;
- 0.25% planned account risk per trade;
- all existing aggregate risk, daily/weekly loss, correlation, liquidity, stale-data, stop, and cooldown guards unchanged.

No profit-protection/trailing change is included in R2. That is deliberately reserved as a separate later hypothesis so results remain attributable.

## Research infrastructure state

The natural rollout-verification plan is complete.

Natural research campaign `35420465214` passed both required production verifier gates:

- `Verify root+challenger rollout contract before authoritative publish` succeeded inside evaluation;
- the independent final rollout verifier also succeeded;
- root/challenger execution, authenticated shared capture, authority refresh, registry publication, and dashboard dispatch completed without manual evidence creation or guard weakening.

The rollout verifier is being generalized so the same authenticated contract applies to R2 rather than silently skipping new candidate identities.

R2 registration is being changed so the candidate is pinned to the exact `main` commit that contains its strategy implementation while the old root and R1 candidates keep their immutable historical code revisions.

## Locked R2 research gates

At **20 closed R2 research trades**, apply the precommitted futility rule only:

- reject if `P(mu > 0) < 0.05`;
- otherwise continue without declaring success.

Do not label R2 `RESEARCH_PROMISING` before all are true:

- at least **40 closed R2 research trades**;
- at least **7 distinct closed-trade UTC days**;
- `P(mu > 0) >= 0.80`;
- complete modeled fees/funding/slippage;
- no integrity, contamination, or hard-risk issue.

Positive touched research is never direct promotion.

If R2 becomes legitimately promising, freeze a new immutable candidate and start a new clean untouched validation period only after inherited touched-period handling and the documented embargo. The old V4 corpus cannot be reused as that clean sample.

## Exact next action

1. Finish the R2 code/registration/verifier changes under TDD and require compile, Ruff, mypy, full pytest, and research smoke on the exact branch head.
2. Merge only the exact reviewed green head and require fresh `main` CI.
3. Verify the automatic R2 registration push publishes an authenticated authoritative research registry and the research dashboard exposes R2.
4. Do **not** manually dispatch an economic cohort merely to get a result.
5. Let the safe-gap dispatcher create future research captures naturally under the existing daily success cap.
6. Observe the implemented authoritative V4 interval/completeness synchronization path before admitting subsequent research economics; actual historical interval coverage/disjointness remains authority.
7. Require the pre-publication and independent final rollout verifiers on root+R2 cohorts.
8. Apply the locked futility/promising rules exactly as written.
9. If R2 fails, define the next single-variable challenger from forward failure evidence rather than forcing activity.
10. Keep Phase 10 and live trading blocked until a future untouched candidate satisfies every locked promotion gate and the user explicitly authorizes live capital.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in the research lane.
- Do not increase leverage or relax risk limits to rescue negative expectancy.
- Do not present the revealed V4 baseline as untouched OOS or promotion evidence.
- Do not manually create favorable economic samples through retry, extension, backfill, or duplicate same-day research dispatch.
- Do not weaken provenance, replay completeness, authentication, lineage, cost, or risk gates.
- Do not optimize primarily for win rate.

**LIVE TRADING: DISABLED.**
