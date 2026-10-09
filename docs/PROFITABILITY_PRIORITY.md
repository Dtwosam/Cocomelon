# PROFITABILITY FIRST — start here in every new Cocomelon chat

**Standing user directive (2026-10-10): Build autonomously toward a genuinely profitable Hyperliquid trader. Do not ask for routine implementation approvals. The next unit of work should improve verified after-cost expectancy or obtain the missing trustworthy evidence needed to decide whether it does.** Keep hard risk, trading-safety and promotion controls intact.

This is the **top-level current research and handoff checklist**, linked from `README.md`, `AGENTS.md`, `docs/STATUS.md`, and `docs/CHATGPT_PROJECT_SOURCE.md`. It complements, but does not supersede, `AGENTS.md`, `docs/MASTER_SPEC.md`, `docs/DECISIONS.md`, or individual immutable experiment freezes.

## Current financial truth — timestamped, not a live quote

Verified GitHub Issue #469, paper heartbeat **2026-10-09 23:40:16 UTC**, worker **38002307902**, head **d9accd5**, predecessor **38001096314**:

| Measure | Evidence |
| --- | ---: |
| Paper starting equity | $10,000 |
| Paper equity | $9,682.45 |
| **Total paper-account net PnL** | **-$317.55 (-3.18%)** |
| Unique cumulative closed paper trades | 155 |
| Recorded gross realized result | -$200.37 |
| Recorded total fees | $119.22 |
| Recorded funding | $2.05 |
| Currently open paper positions | 0 |
| Live orders | **DISABLED** |

These are *point-in-time operational account figures*, not current forever and not real-money trading results. The cumulative PnL is already after recorded costs; **do not subtract the displayed fee/funding totals again**. Historical completed-trade and evidence authority comes from authentic durable state and journal, not an unverified workflow.

**First action in each future chat:** refresh `https://github.com/Dtwosam/Cocomelon/issues/469`, current `main` head SHA, newest `Continuous Mainnet Paper Trader` workflow run, its trading step, exact successor lineage, and last authenticated durable artifacts. Keep all run/attempt identities in the answer. A merged PR is not automatically deployed to a long-running earlier-head worker.

Latest repository implementation as this handoff was authored: **`ec7285b2c6e00c9e722283479396c038a6fcd643`** (PR #1087), with *both post-merge test/research suites successful*. This is a **historical reference**, not an instruction to check out an outdated commit.

## Definition of progress: money after costs, not code volume

**Primary KPI:** baseline whole-account **net PnL / net expectancy per authentic executed paper trade**, including realized exits, taker fees, funding, slippage, missed executions, gaps, drawdown and cash/opportunity costs. Compare an independent **challenger account** to the **same-window baseline** under identical forward mainnet data; report absolute profitability **and** incremental advantage.

**Supporting diagnostics:** per-direction LONG/SHORT net PnL; per-strategy, market, UTC-hour and rank cohort; loss tail; entry/exit friction; profit factor; risk-adjusted return; fee/gross-profit ratio; capture freshness, unresolved source gaps and duplicate/missing-rank rows. An attractive hypothetical skip-only rule is **not** independent account PnL: it assumes no replacement trades or changed exposure. Separate gross vs net; mark what is descriptive, hypothetical, executed paper, or authenticated paired paper.

**A change earns the label 'profitable' only if** it beats NO_TRADE and the unchanged baseline **after realistic costs** on a sufficiently large *untouched forward* window; independent paired account absolute and incremental net PnL are positive; results survive chronological splits, market/side concentration, leave-one-market/winner perturbations, drawdown and known feed-integrity gates. Use the **frozen experiment-specific numeric thresholds** from the actual candidate specification; never invent a generic small sample cutoff or change a frozen threshold after seeing returns. Fail closed on missing receipts, unfillable L2 paths, old lookahead data, or contaminated market-gap lineage. Passing an investigation gate is **not** execution promotion.

**Live money stays disabled** until the full documented independent live-promotion process is met; no automatic switches, wallet funding, risk increases, martingale, stop weakening, or live-order activation as an optimization shortcut.

## Ranked work that is likely to matter financially

1. **Measure why the baseline loses:** use *all* unique executed journal trades and authentic decision-time rank/context; reconcile gross PnL, fees, funding and net cash/return by LONG/SHORT, strategy, rank and entry/exit context. Keep losers with missing evidence in original account totals and clearly expose the missingness. Prefer high-dollar, reproducible loss concentrations over speculative micro-optimizations.
2. **Finish the already-frozen SHORT breakout rank experiment instead of inventing new filters:** historical audit of 153 paper closes found top-3 SHORT breakout: **4 trades, about +$86.31 net**; lower-ranked breakout: **8 trades, about -$54.73 net**. This is **tiny retrospective discovery only**. Candidate `prospective-short-breakout-only-top3-v1` is paper-only, frozen and embargoed; forward selective-trade analysis requires its original clean 40-trade/side/market/block checks and an independent full-account paired paper trial before ever modifying the trader. Do not conflate the 153-trade discovery snapshot with the newer 155-trade paper heartbeat.
3. **Review the existing loss-context paired account challenger on equal forward time windows:** the old trial had **6,215 flattened v1 gap intervals and 642 unresolved** and negative *relative* net account results. Old contaminated results must not be counted as clean. The independent `loss-context-paired-portfolio-shadow-scoped-v2` starts flat with market-scoped v2 gaps. Keep baseline and challenger account state/fees/funding isolated and produce real comparable returns, including both directions. No retroactive promotion of v1.
4. **Unblock exact, trustworthy candidate exits only when there are scoreable opportunities:** reopened LONG+trend 5m last posted **5 exact exits**, ~**-$1.83 after costs**, gate failed; 15m last posted **0 exact exits**. Do not report 5m or 15m as promising based on gross chart moves. Later research workflows correctly refuse 1.62 GB legacy archives over the 512 MiB budget. A producer must supply an authenticated small exact-source artifact and pass content integrity.
5. **Close the specific evidence-integrity obstacles that block an otherwise economic decision:** a post-handoff full-stack rebuild reported **1,578 risk-rejected rows, 67 missing-rank observations, risk_rejected_integrity_clean=false**. The merged source diagnostics (#1085) report missing required files/dirs after handoff; stricter research-only validation (#1087) rejects dirty source summaries, bad digests and drift. Read the **first real producer preflight artifact** when available; fix its exact named issue, not an assumed missing producer. The paper code already writes the LONG-trend source before handoff. Never invent historical L2, rank, fills, or repair anonymous legacy gaps.
6. **Minimize work not connected to an economic decision:** prioritize one high-value testable economic hypothesis and its after-cost outcome at a time. Reliability work remains necessary only when it blocks safe paper continuation or defensible research, with a named blocker and a measurable exit criterion.

## Mandatory work loop for an autonomous new chat

1. **Refresh reality first.** Verify exact repo SHA, worker heartbeat (#469), active paper workflow/trader health, latest durable journal/account results, PRs, research-gate artifacts and shadow account forward outcomes. State timestamps and data provenance; never guess from old screenshots or chat summaries.
2. **Pick the highest expected-value *unblocked* profitability question.** Prefer an existing frozen challenger or clear loss attribution. Record the particular net-dollar/after-fee opportunity, comparison baseline, sample size, original scope, expected evidence and a falsification criterion.
3. **Make one contained research or paper-only code change** on a fresh branch. Use strict replay/decision-time boundaries; preserve *all original trades*, loser inclusion, source integrity, exact frozen state, fees/funding, exits and risk veto. Reject impossible inputs rather than silently zeroing costs or treating absent trades as winners.
4. **Run full exact-head `test` and `research` CI**, fix any failures, merge only when green, then confirm post-merge CI and worker code adoption. Do not disrupt the active stateful paper worker for expedience. A pending diagnostic is pending, not success.
5. **Report the economics, not the number of PRs.** At minimum report: worker/time/head, equity, total net PnL, closes; baseline vs challenger same-window net PnL and drawdown (if available); fees/funding; forward sample, markets, directions and data-completeness; gate PASS/FAIL and next concrete priority. If no qualifying evidence is available, say **NO PROFITABLE EDGE VERIFIED**.

## Fast source map for a new chat

- `AGENTS.md`: mandatory safety/engineering hierarchy and heartbeat rules.
- `docs/MASTER_SPEC.md`: permanent product, risk and evaluation specifications.
- `docs/DECISIONS.md`: frozen candidate and evidence contracts (especially rank-filter D-087, paired-account D-088, worker heartbeat D-089).
- `docs/STATUS.md`: historical development log; **read the top profitability handoff first**, not its thousands of stale phase notes.
- `docs/CHATGPT_PROJECT_SOURCE.md`: portable project bootstrap; starts with the same profitability directive.
- GitHub issue [#469](https://github.com/Dtwosam/Cocomelon/issues/469): current running paper account heartbeat.
- `src/cocomelon/research/prospective_short_breakout_rank.py`: frozen SHORT rank challenger.
- `src/cocomelon/research/loss_context_paired_portfolio_shadow.py`: paired account mechanism.
- `scripts/verify_compact_long_trend_exact_source.py`: authenticated preflight and missing/integrity reasons.

**Do the work autonomously, but do not conflate autonomy with permission to put real capital at risk. The next chat should begin from after-cost evidence and ship a falsifiable improvement, rather than repeating the same infrastructure-status loop.**
