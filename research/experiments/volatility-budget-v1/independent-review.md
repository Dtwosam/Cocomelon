# Independent review of the final inactive volatility binding


**Verdict: no remaining actionable defect found in the reviewed corrected inactive binding.** This section supersedes all interim approvals and holds above. It approves only the library/test scope. Operational activation remains BLOCKED, and the parent must still commit these exact bytes, obtain both full and research CI success at that new head, review the final diff and verify the merged head. The old green bce62c72 CI does not substitute for the new run.

Final independently verified SHA256:

- Pure policy module: `378d04b6bdc55b0e5271821f69d04306c3e0b2f17cc93eb11fe41fc55f4b83fe`.
- PAPER lifecycle: `b9535e69d3ffdd8f886b16ee4b43d04744f0e65975c0c8df6d8c81ff93bc6e9a`.
- Policy tests: `9f50325d837d2072d0a5de467b97576b6ff6d97066ab1099fbaabc8798c10531`.
- Lifecycle tests: `605df8a2bdf4fc7bc687d69bb390dbce83e095c7c00ada1671ae01fe17c9e7b8`.
- Frozen policy bytes, unchanged: `eca2816e42a1a0409737e179b45761a8a4ad0ebb2149ee7ad956b6867caffdaa`.

Independent final local verification: **258 tests passed in 4.01 seconds**, using Python 3.12, covering both volatility suites, existing flow policy/lifecycle, risk engine/invariants and PAPER funding/accounting. The two volatility suites contain 120 passing cases. Independent standalone reproducers also confirmed full-close, partial-close and no-fill commit-before-checkpoint recovery, correct residual marked equity, the permanent partial-exit loss floor after a recovering mark, and post-opening-mark commit recovery.

All nine concrete findings are resolved in these bytes:

1. Canonical selection distinguishes current eligibility from later funding/cost/execution veto; the selected batch cannot substitute another market.
2. Actual opening requires a genuine fresh positive mark/oracle context.
3. A mark-only stop crossing remains latched through later recovery and restart.
4. Mirrored lifecycle revision/digest witnesses reject trial-only checkpoint rollback; immutable fills and accounting reject account history rollback.
5. A staged opening expires on tick/advance at the frozen two-second deadline without chasing.
6. Actual execution books require valid schema, unique positive levels and both fresh original clocks.
7. The original known opening mark is pinned before execution and reconciled at actual fill, including commit/restart gaps; its stop and permanent marked floor cannot disappear before a recovering mark.
8. Custody highwaters compare only immutable histories, allowing legitimate flat-position deletion and rolling-peak pruning. Exact witnessed mark transitions reconcile same-clock commits while conflicting transitions still reject.
9. Each actual reduction witnesses its original context, pre-position, cash, time and book key before IOC. Partial residual exposure is revalued with correct unrealized PnL, gross notional and margin. Historical marked equity and the permanent floor survive an interrupted partial commit even when the account already has a newer recovering mark.

For the final partial-exit safety reproducer, the corrected account records known marked equity 9946.88619870130 and latches permanent suspension; a later recovering mark cannot clear it. Partial commit recovery also preserves a newer current mark rather than replacing it with a stale historical receipt. Historical contexts are validated at their actual fill/attempt time, never admitted as fresh at restart, and never re-ingressed with rewritten receipt clocks. A recovered reduction created from a fresh book at T+12000 cannot fill at T+12200 and may fill on the fresh book at T+12300, preserving its actual new 250 ms latency. Stale/unknown partial context disables qualification and entries while protective reductions continue.

No generic ordinary execution/accounting/risk module was edited for these corrections. The frozen E-based geometry, existing actual-quote IOC anchor, stricter 59 bp sizing reserve and 0.10% planned-risk ceiling remain intact. No new operational account, T0, first-entry boundary, launcher, worker workflow, network transport, venue order endpoint or LIVE path is approved.

The independent existing free 24-hour owner, aggregate egress budget and durable original-source/restart custody are still unverified. Local witnesses cannot certify coherent whole-directory rollback/cloning protection. Original candle response custody remains an operational caller obligation, not a property established by synthetic inputs or evidence hashes. No qualifying economic result or profitable edge is verified.

## IOC interpretation

Frozen wording specifies reuse of the existing depth-aware IOC and a25bp cap without explicitly anchoring that cap to decision reference E. Existing IOC semantics anchor its depth limit to the actual attempt executable quote. Current top-quote admission also rejects adverse movement beyond E25bp; deepest IOC levels can consequently be approximately50bp adverse to E. The frozen E-based stop/target never reanchors. Risk is re-sized against the actual top quote and fixed stop with the stricter59bp reserve, and each actual fill is independently clipped to approved notional and planned-risk ceilings. This does not bypass the0.10% planned-risk limit; gaps/slippage/future funding can still exceed planned realized loss. Silently tightening the whole IOC to E25bp would add a policy admission rule not explicitly stated in the freeze; the reviewed interpretation preserves the existing adapter semantics.
