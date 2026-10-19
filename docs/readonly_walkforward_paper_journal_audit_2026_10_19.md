# October 19 — make after-cost walk-forward research runnable on a closed original PAPER journal

## Profit problem and provenance

At 19:45 UTC, the authenticated ongoing PAPER worker #39292750327
reported **$9,771.44** equity from $10,000 start, or **−$228.56**
marked PnL after paid fees and funding. There were **307 completed
trades**, gross realized +$11.10 and booked fees $239.51. The research
v3 original market source remained **FAILED**, with 2,204,070 rows
dropped. The running worker is on prior SHA `5ed178dd`, so this code
has not affected its decisions.

PR #1387 already froze a new after-cost empirical admission hypothesis,
using original PAPER trade `net_r` values strictly from fully closed
baseline positions opened AFTER the six-hour embargo and closed
strictly BEFORE a proposed entry. This new offline adapter connects
that research rule to a *real canonical SQLite trade journal* rather
than synthetic in-memory objects or hypothetically profitable markouts.

## Safe read-only audit

`JournalStore(path, read_only=True)` checks the exact existing schema
metadata and table set **without creating a missing DB, modifying
records or applying migrations**. It opens the authoritative store with
SQLite `mode=ro` and `PRAGMA query_only`. The special asynchronous
trade writer, which otherwise opens a new write connection by file path,
explicitly refuses use on the read-only store.

The CLI `scripts/audit_readonly_prospective_net_edge_journal.py`:

- Requires an exact ORIGINAL completed journal and an explicit
  `--freeze-ms` chosen before the proposed trading cohort, plus
  a **new** output path.
- Refuses SQLite WAL, SHM, or rollback journal sidecars. An active
  uncheckpointed database cannot be promoted as a sealed offline input.
- Runs SQLite `PRAGMA integrity_check`, canonical trade-ID and after-cost
  cash/R reconciliation through the production trade decoder, and hashes
  the source bytes both before and after study.
- Emits a SHA256-labelled, non-overwriting JSON research receipt with all
  later proposed entries and their strictly prior reference counts,
  eligibility and same-fill *hypothetical* outcomes. The output does
  NOT recast deferred, unfunded or skipped hypothetical entries as
  independently profitable account equity.
- Explicitly marks independent source authentication, 72-hour v3 market
  completeness, capital-matched PAPER challenger, positive absolute
  after-cost whole-account equity, and execution/promotion authority
  **FALSE**.

Example against a **completed immutable offline archive** (not the
running PAPER state):

```bash
python scripts/audit_readonly_prospective_net_edge_journal.py \
  /path/to/complete-paper-journal.sqlite3 \
  --freeze-ms 1792436400000 \
  --json-out /path/to/new-net-edge-evaluation.json
```

Do **not** treat the example freeze time as an endorsement: use a
registered actual freeze and embargo for the future test.

## Real success criterion

The CLI only prevents lookahead and source-account mutation in research.
It does not simulate new fills or create a new independent portfolio.
A genuinely profitable strategy would require NEW prospective,
predeclared opportunity/entry decisions with original first-received
market source complete for >=72h, matched independently funded PAPER
cash accounts, paid maker/IOC fees, spread, slippage, funding, missed
orders and realistic margin occupancy, and strictly POSITIVE absolute
ending equity after all costs. Existing failed historical candidates
cannot be reused as success.

No active worker restart, baseline cash reset, risk change, fees rewrite,
original timestamp adjustment, or LIVE order permission is introduced.
