# October 19 — avoid archived receipt API scans on missing source

At 17:40 UTC the scheduled first-failure-receipt workflow failed at
**Restore previous first-failure receipts** with GitHub installation HTTP
403 rate exhaustion even when no canonical source readiness manifest
was admitted. That step ran unconditionally, scanning up to 100 previous
successful workflow runs and their artifacts despite there being no
eligible new receipt to append.

The historical immutable first-failure ledger is important: it prevents
retesting failed strategies as if losses never happened. The fix does NOT
drop, reset, rewrite or replace that ledger.

- If and only if `steps.source.outputs.ready == 'true'`, perform the old
  historical restore, verify existing immutable receipts, and allow the
  append-only updater to run.
- If the source is missing, invalid or unqualified, skip all historical
  receipt lookups and go straight to the **BLOCKED** status and required
  failing integrity step with execution/promotion authority false.
- The workflow remains capable of failing to publish issue status if the
  shared installation token is entirely exhausted; this must not be
  misrepresented as a successful model evaluation.
- No trade selection, orders, risk parameters, account cash,
  source-clock timestamps, restored old v5/v2 campaigns, worker restart,
  or LIVE permission is changed.

The present PAPER account remains negative after costs, and source v3
capture remains failed. This is a research-control load fix, not proof
that any candidate strategy can beat the per-trade gross-return hurdle.
