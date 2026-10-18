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

## Second intervention — 14:34–14:38 UTC quota recurrence

The first throttle was insufficient: independent original GitHub Actions
job logs from **October 18, 14:34–14:38 UTC** record HTTP 403
`API rate limit exceeded for installation` while attempting to
authenticate exactly pinned account-evidence and decision-learning
artifacts. Examples:

- [Research cycle #39136491653](https://github.com/Dtwosam/Cocomelon/actions/runs/39136491653):
  exact learning-state authentication rejected at the GitHub API.
- [Learning catch-up #39136491781](https://github.com/Dtwosam/Cocomelon/actions/runs/39136491781):
  exact original PAPER source discovery rejected by the same API cap.
- [Decision catch-up #39136884964](https://github.com/Dtwosam/Cocomelon/actions/runs/39136884964):
  decision-source discovery rejected by that API cap.

Those failures do **not** mean missing trades, valid v3 original source,
profitable baseline or a promoted challenger. They mean the
installation-wide control plane is oversubscribed; the required
authenticated economic comparisons cannot be made by those jobs.
No true source is recreated, accepted without a digest or cached from
an untrusted workflow name.

Three other high-frequency **redundant** fallback loops have
event-driven source wakeups and manual recovery. Their polling
frequencies were therefore reduced without changing the source gates:

| Redundant fallback workflow | Before | After | Starts/hour |
| --- | --- | --- | ---: |
| Continuous PAPER learning catch-up | every 15m | :07 hourly | 4 → 1 |
| Research learning catch-up | every 10m | :27 hourly | 6 → 1 |
| Research clean-state catch-up | every 10m | :47 hourly | 6 → 1 |

Together with the *first three* already-hourly safety nets (:13, :17,
:41), this cuts fallback schedule starts from **36 to 6 per hour**
(83.3% fewer). The extra three alone drop from **16 to 3 per hour**
(81.25% fewer). This does **not** guarantee the shared installation
quota will recover: event-driven followers, full-pagination scans and
external callers also spend the same installation budget.

Each workflow retains the original `workflow_run` arrival events,
manual `workflow_dispatch`, one-at-a-time concurrency, trusted
source/ZIP/receipt/digest checks, fixed candidate IDs and fail-closed
economic eligibility. On an event-driven success, it still runs
immediately; the hourly schedules are missed-event recovery only.
Nothing in the original PAPER position book, risk, fee, source archive,
cash ledger, trading worker lifetime or LIVE mode changes. A
successful future control-plane job is **not** positive after-cost
whole-account PnL.

**Return gate remains unchanged:** at the last authenticated PAPER
observation before this second API-budget fix, account equity was
$9,736.88 from $10,000 (−$263.12 whole-account net), with 291 closed
trades and failed original-v3 clock/gap evidence. Profitability
requires new genuine source and independent matched-account economic
records, not a green catch-up run.
