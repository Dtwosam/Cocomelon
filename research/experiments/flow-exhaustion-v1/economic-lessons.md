# Economic lessons and an exploratory mechanism

This is historical ordinary PAPER evidence plus an explicitly unvalidated prospective hypothesis. It establishes neither historical participant causation nor a profitable new edge. **NO NEW ECONOMIC PROGRESS.**

## Evidence and verification

The canonical source is the completed 321-trade ordinary PAPER journal from worker `39410259494`, artifact `12276107857`. Its manifest records SHA-256 `7bf6f17a1632558258288f0e2769991d7136731c752bf5da8a64e9c1fbe40a0f`, 2,959,114,240 bytes, and the preservation of all 319 preceding canonical payloads plus two additional losing closes. This is a historical boundary, not the present heartbeat count or marked account.

Sources:

- `research/audits/2026-10-20-autonomous-trade-learning/economics/terminal-manifest.json`
- `research/audits/2026-10-20-autonomous-trade-learning/economics/aggregate-results.json`
- `research/audits/2026-10-20-economic-mechanism-discovery/trade-intelligence/aggregate-identifiability.json`
- `research/audits/2026-10-20-profitability-deadlock/continuation/aggregate-results.json`

For this review, the original local `terminal-321-extracted/journal.sqlite3` was reopened with SQLite URI `mode=ro` and `PRAGMA query_only=1`. All 321 `journal_trades.payload_json` rows were read; outcome groups and money identities were independently summed using 80-digit Decimal arithmetic. No individual IDs, private payloads, or account identities were exported. The 2.96 GB journal hash is inherited from the authenticated custody manifest; this review does not claim another fresh full-file hash or independent authentication of original capture.

| Historical group | Closes | Actual-fill gross | Actual fees | Booked funding | Booked net |
| --- | ---: | ---: | ---: | ---: | ---: |
| Winners | 91 | +$1,587.736253 | $67.482394 | -$2.546112 | +$1,517.707747 |
| Losers | 230 | -$1,684.690270 | $181.342510 | -$0.404969 | -$1,866.437748 |
| All | 321 | -$96.954017 | $248.824903 | -$2.951081 | -$348.730001 |

`Net = actual-fill gross - entry fees - exit fees + booked funding`. The total residual is only `-4.0E-28` dollars, matching preserved producer rounding. Fill-to-fill gross already embeds execution prices: do not subtract the $129.737975 reference-relative signed slippage again. Reference-price gross of +$32.783957 is a bookkeeping diagnostic, not capturable alpha. The reference movement required to cover recorded friction averaged 13.7889 bp of entry notional; approximately 9 bp was fees.

Funding is incomplete: 748 scheduled hourly boundaries comprise 547 booked, 187 explicit gaps, and 14 unknown boundaries. These gaps affect 117 trades. Unbooked funding cash is UNKNOWN, never zero. Thus the table is accurate **as booked**, not certified after every economic cost. All 321 decisions joined; 314 have feature objects and seven lack features. Only 70 have producer-complete excursion records; 251 remain path-incomplete. Even producer-complete means no known internal gap, not continuous executable quotes or independent venue completeness.

## A. Lessons from winners

Profitable directional opportunities existed on both sides: 43 LONG and 48 SHORT winners. Their actual-fill gross was substantial enough to pay their recorded fees and funding. Median signed fill-to-fill movement was +144.9906 bp; median holding time was 235.2178 minutes. This shows the account sometimes captured moves much larger than its normal fee hurdle. It does not show which pre-entry participant condition predicted them, nor justify choosing a four-hour hold from an outcome-conditioned median.

78 of the 91 winners closed with `MARK_STOP_TRIGGERED`; the other 13 used `OPPOSITE_FRESH_THESIS`. A stop-trigger label therefore does not itself mean the economic trade failed: a protective or trailing stop can realize profit. The largest winner was +$113.994912. Its contribution is real; removing winners is only a concentration sensitivity, never an executable entry rule.

The 70 early producer-complete records have 60 recorded best marks above entry plus nominal entry/exit fees, yet 44 of those closed nonpositive. This refutes the blanket explanation that all these entries never moved enough to clear nominal fees. It does not prove that those marks were executable, observable as optimal exits, or recoverable through a new exit rule. Those records opened only September 26–October 1 and are a selected early subset; no representative path claim follows. Six stored zero-MFE-currency values clamp genuinely adverse best marks and must not be interpreted as breakeven observations.

**Economic conjectures suggested, not established:** durable allocation or informed demand could sustain some large moves; temporary liquidity demand followed by absorption could create some favorable excursions that later disappear. Historical extrema do not distinguish these explanations. A future experiment should observe the flow-and-liquidity sequence before entering, rather than label a winner afterward.

## B. Lessons from losers

There were 107 LONG and 123 SHORT losses. Median signed fill-to-fill movement was -80.9068 bp and median holding time 64.26085 minutes. These are outcome descriptions, not grounds for banning LONGs or holding losses longer. 221 of 230 losses already had negative actual-fill gross; only nine had positive gross flipped negative by fees/funding, totaling -$4.110563 net. Fee reduction alone does not explain or repair the main failure. Even refunding every recorded fee leaves the full 321-trade book at -$99.905098.

203 losses used `MARK_STOP_TRIGGERED`; this does not identify whether the cause was false continuation, changing information, temporary pressure, execution, stop geometry, or several together. Missing paths prevent assigning precise causal fractions. Ten recorded losses exceeded their approved risk ceilings, so prospective sizing must include costs and gaps and retain hard lockouts rather than assume planned risk bounds realized losses.

Chronological thirds retain all 107 trades each: -$245.741392, -$136.563314, and +$33.574704 net. The latest improvement is preserved; without its largest winner it is -$80.420207. These results neither establish positive forward expectancy nor prove every positively skewed strategy invalid. The lifecycles form 69 overlapping components and span five natural close weeks; 321 trades are not 321 independent market shocks.

## C. Three distinct participant hypotheses

1. **Temporary immediacy pressure and liquidity recovery — selected exploratory hypothesis.** An aggressive buyer/seller pays for immediate execution and temporarily displaces price when displayed liquidity is scarce. Passive liquidity suppliers can subsequently absorb continuing demand and restore visible depth. Once same-direction flow weakens and opposing liquidity visibly recovers, part of the displacement may reverse. The hypothesized payer is the immediacy demander; the risk-bearing service is waiting through inventory and information uncertainty. This is a conjecture about observable aggregate behavior, not proof of participants' identities or motives.
2. **Durable informational or allocation demand — competing continuation explanation.** Informed participants or persistent portfolio rebalancing repeatedly consume new liquidity because their desired inventory change lasts longer than the initial price move. Replenished quotes may simply be consumed again, with price accepting a new level. This could explain large winners and why indiscriminately fading every shock fails. No informed-trader label, TWAP identity, or mandate can be inferred from the historical journal or untagged tape.
3. **Leveraged-inventory contraction — competing deleveraging explanation.** Risk-constrained position holders reduce exposure during adverse movement, potentially extending pressure as open interest contracts and liquidity withdraws. The price path may continue until that adjustment subsides, then normalize. Funding, OI, actual signed trades, and books would have to distinguish this from new-position demand. Falling OI is not a liquidation identifier; no historical forced liquidation is claimed.

These mechanisms imply different relationships between executed flow, price impact, liquidity recovery, and subsequent movement. They are not three parameterizations of one candle pattern. The 321-row export has zero identified external participant-intent/obligation fields and zero complete common-clock executable post-entry paths, so none can be asserted as the historical cause.

## D. Why select hypothesis 1 for a fresh PAPER trial

Its observable economic question can be tested with genuine future native trades and L2 observations, without private wallet identity, an inaccessible event archive, or proof of profitability beforehand. Both directions remain eligible. The prior discussion at `research/audits/2026-10-20-continued-conditional-discovery/economics/README.md`, lines 86–100, explicitly considered **temporary inventory pressure followed by measured liquidity recovery** and classified the necessary historical evidence as missing; it did not run and reject this policy. Historical source failure remains preserved. The current user instruction permits a fresh isolated exploratory PAPER test and supersedes the old requirement to prove returns before admission.

The actual executable distinction must survive implementation: native signed executed trades establish pressure; ordered genuine L2 observations establish *observed depth recovery before entry*. A mere price reversal, static imbalance, range reclaim, or candle volume surprise is insufficient. L2 snapshots are not order-by-order queue records: do not call recovered displayed depth proof of the same maker replenishing, infer hidden liquidity, or manufacture cancel events. Do not infer liquidation or TWAP identity from untagged prints. The existing IOC paper execution can trade the hypothesis without granting unsupported maker fills or rebates.

Freeze the pressure window, past-only anchor, shock size, signed-flow concentration, recovery confirmation, target/stop, time limit, cost assumptions, market scope and disabling rules before prospective outcomes. Choose their initial values from economic scale and the need for meaningful headroom beyond roughly 9 bp fees plus actual spreads/slippage/funding, with explicit acknowledgement that those initial choices remain unvalidated. Never select them from the winning-trade duration, historical MFE, market winners, or a best-performing grid. Position and stop rules must protect against hypothesis 2 or 3 dominating.

**Strongest falsification:** with complete future observation and realistic delayed IOC fills, the defined pressure-plus-recovery episodes do not deliver positive absolute whole-account net returns against the capital-matched NO_TRADE control, or the predeclared chronological/independent-shock robustness requirements fail. Report largest-winner removal as concentration sensitivity; by itself it does not disprove a positively skewed mechanism. Diagnose the intermediate predictions too: if observed recovery does not precede normalization, the mechanism fails; if prices normalize but entry/exit/costs consume it, this executable strategy fails economically. Missing source, funding, fills, or equity history makes the result unqualified, not profitable. A no-fill/no-entry trial is inconclusive about returns and must preserve its full denominator.

The minimum 72 hours and adequate independent samples are requirements for a validated-edge claim, not permission to begin the controlled trial. No prospective profit, causal benefit, activation or validation is asserted by this draft.
