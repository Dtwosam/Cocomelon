# PAPER rollover stop-cause witness — October 18, 2026

## Actual authenticated predecessor failure

The genuine [PAPER run #39103876679](https://github.com/Dtwosam/Cocomelon/actions/runs/39103876679)
produced GitHub original trader failure artifact
`continuous-paper-trader-failure-39103876679-1`,
SHA-256
`4e8139b73586c47af56aab1659c18d50ce2f3fc28286fbbeadc7639d2c1748c7`.
The decoded immutable tiny receipt shows:

- `trader_exit_code=143` and `failure_class=trader`;
- `upgrade_stop_requested=true`;
- heartbeat reader and tee each returned zero, with 427 heartbeat lines;
- account parity, original source and after-cost economics **not inferred**.

The archived text also exposed an independent format bug: Bash used
`printf` format strings containing literal double backslashes before `n`,
so the receipt contained the printable sequence `\\n` between fields rather
than one newline per key/value row. **Old evidence is not rewritten.** The
new failure writer now uses real newline-delimited rows; a shell execution
test rejects another malformed receipt and verifies that negative economic
and LIVE authority flags remain exact and false.

The ordinary worker's unconditional 4h15m session-overrun watchdog and
the **opt-in-only** main-push upgrade path both call the *same*
`request_runtime_handoff` shell function and touch the **same**
`/tmp/continuous-paper-upgrade-requested` stop file. The existing
receipt cannot tell which trigger fired. This is **not proof** that an
ordinary code push illegally restarted PAPER; no such claim is made.
Issue #469's last authenticated 10:25 UTC equity was **$9,758.81**
(marked net **-$241.19** from $10,000). A newer workflow running
the trader is not independent evidence of successfully restored
economic account parity or future profitability.

## Next-worker diagnostic fix

The existing handoff function writes a best-effort local anonymous
**`handoff_trigger`** marker before requesting the original stop:

- `session-overrun-watchdog` for the existing 4h15m watchdog;
- `opt-in-main-push` for the optional numeric GitHub replacement run ID;
- `unclassified` for any invalid, missing or uncertain caller.

If the stop file is absent, a failed trader's receipt records
`none-observed`. If the stop file exists but the bounded marker is
missing/invalid, the receipt records `unclassified`. No GitHub text,
market data, API secrets, paths, or unchecked strings are published.
The marker is purely negative operational evidence. No retry, trigger,
deadline, stop signal, GitHub runner clock, executable, fee schedule,
account-state checkpoint, original capture, or PAPER/LIVE trade changes.

The nonzero trader exit still **fails the Actions step** and is
independently archived; even a known natural-overrun marker cannot
falsely convert a broken or interrupted PAPER session into a green
source, a successful successor, a 72h experiment, or positive account
PnL.

Unit tests run the actual extracted bash trigger classifier against
valid and adversarial input without starting/stopping the trader.
They also require the original opt-in guard, 15300-second unconditional
safety watchdog, existing INT/TERM escalations, immutable fail-closed
exit receipt and exact false-profit/LIVE flags.

## Profitability priority

The original v3 research source for that predecessor had failed clock
regressions, millions of dropped original records and real L2 source
gaps, so it cannot be rescued. New source-valid continuous 72h
market evidence and matched after-cost absolute positive PAPER returns
remain **unverified**. The next genuine rollover failure receipt can
identify whether to optimize slow final cleanup versus investigate an
unexpected code-push stop, avoiding risk to real PAPER source/account
continuity. This is a diagnosis, not a profitability improvement.
