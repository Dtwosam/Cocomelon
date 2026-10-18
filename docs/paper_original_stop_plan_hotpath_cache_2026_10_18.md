# PAPER L2 hot-path: cached original stop plan (October 18, 2026)

## Why this changes a real bottleneck

Authenticated original PAPER worker #39120486505 at 14:21 UTC had
**291 closed trades, $9,736.88 whole-account equity, -$263.12 net
after costs**. Its latest decision batch showed **16 stale books** and
**zero markets deep-ready**. The same worker recorded a maximum
**1,060 ms** synchronous `position_mark_original_stop_book`
research callback, contributing to the `mark_account` maximum of
1,069 ms, while its WebSocket original-v3 source already failed on
massive original receive-clock regressions and source gaps. A single
optional research callback must not repeatedly contend with the
event loop when data freshness matters to actual PAPER trade selection.

## Scoped change

`OriginalStopBookCapture._plan_for` previously called the synchronous
backing `opening_plan_loader` on **every active mark**, despite
`PaperOrderPlan` being a frozen dataclass and its original stop never
changing. A new **128-entry bounded LRU** caches ONLY plans that were
successfully validated against the **exact immutable opening_plan_id**,
original market, non-reduce-only opening and presence of its original
stop. After startup/restart/eviction, a plan is loaded and checked again.
Missing, stale/wrong-ID, or invalid plans fail closed as before.
The durable pending/evidence stores remain authoritative and their
reads, original stop-crossing timestamps, market event order, plan-stage
and IOC book-capture paths are unchanged. No negative or failed original
plan is cached.

Unit tests verify 20 marks require only **one** backing lookup,
the original crossing price/timestamp and durable evidence are unchanged,
fresh restart reloads, eviction is bounded, and wrong-ID plans cannot
silently enter any study. This removes repeated synchronous storage
lookups but we have NOT measured an actual future PnL or L2 latency
improvement; one earlier 1.06-second observed stall is not proof that
this optimization caused all or even most of its duration.

## Capital and integrity

No changes to actual PAPER pipeline entries, risk approvals, position
marking/exits, stops, fees, funding, leverage, selection strategy,
original v3 receipt time or source admission, account reset or LIVE
trading authority. Original-v3 market evidence remains irreversibly
invalid. The only eligible future LONG-trend challenger remains the
previously frozen independently capital-matched 72h PAPER pair and
requires **positive absolute after-cost whole-account performance**,
clean source and honest account continuity; no new edge is claimed.
