# Profitability-evidence GitHub API budget — 2026-10-18

## Production observation

On **2026-10-18 09:34–09:56 UTC**, independently scheduled economic/research
workflows failed with explicit GitHub installation **HTTP 403 API rate limit
exceeded**. Authenticated examples include continuous PAPER decision-learning
catch-up run `39117168031` and trade-quality readiness run `39115831640`.
These failures interrupt our ability to assess forward after-cost expectancy;
they are not evidence for or against a strategy. Ordinary PAPER worker
`39103876679` was still trading at 10:14 UTC with 288 closed trades and
marked whole-account net PnL around **-$231.73**. The original v3 source
remained irreversibly failed, so no valid 72h v3 result was present.

## Narrow mitigation

Only three **redundant fallback schedule** triggers are rate-limited:

| Workflow | Former cron | New UTC cron | Scheduled runs / hour |
| --- | --- | --- | ---: |
| Research dashboard catch-up dispatcher | Every 5 min | :13 hourly | 12 → 1 |
| Continuous PAPER decision learning catch-up | Every 15 min | :17 hourly | 4 → 1 |
| Prospective cadence/actual trade overlap | Every 15 min | :41 hourly | 4 → 1 |

Together this reduces fallback job starts from **20 to 3 per hour** (85%
fewer). A given job can still perform multiple API calls. This is a limited,
measurable reduction in avoidable contention, **not a guaranteed quota fix**.

The event-driven `workflow_run` and manual `workflow_dispatch` triggers
remain intact for the two PAPER-sourced research followers; their immutable
source, ledger, receipt, and fail-closed gates remain untouched. The dashboard
still has its separate normal event-driven refresh workflow; this catch-up
dispatcher only supplies an hourly missed-event safety net.

## Economics and safety

No new entry filter, optimizer, backtest, trade, fee rule, signal, leverage,
position, account reset, source record, model promotion, or LIVE order.
The unchanged PAPER worker is **not restarted** to apply a YAML schedule
change. All prior failures remain visible.

Next: observe whether HTTP 403 failures become less frequent after the
next installation-quota recovery window, then work on a **source-valid,
72h+ independently capital-matched v3 LONG-trend exclusion PAPER pair**.
Only after-cost positive absolute whole-account results with clean original
source and two correctly reconciled accounts could qualify a strategy.
A green workflow or fewer API calls is not positive PnL.
