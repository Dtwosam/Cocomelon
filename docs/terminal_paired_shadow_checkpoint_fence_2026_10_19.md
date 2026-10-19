# October 19 — terminal paired PAPER checkpoint must reject later research mutations

## What failed economically

Real authenticated paired research states are not fit for trading promotion:
the frozen v5 loss-context paired actor reports `paired shadow durable account
state mismatch`. An independent October 13 ZIP comparison identified a
signed research checkpoint whose account IDs matched its stores in one
original archive, followed by later SQLite accounts advanced about 13.6
minutes with **no matching new signed state** in the successor archive.
A later mismatch cannot be retroactively patched, and the existing failed
v5 portfolio remains failed forever. The separate v2 trend paired actor
likewise has a distinct `received_gap_witness_diverged` failure. Neither
has trustworthy current capital-matched after-cost returns.

## Strict, forward-only software prevention

The ordinary final-paper cleanup now calls the research actor's
`terminal_checkpoint`, not its reusable in-session `checkpoint`.
This atomically closes new research mutation admission *before* queuing the
terminal signed checkpoint:

- All **already accepted** record, rank, reconcile and warmup commands
  stay ahead of the final checkpoint in the same serialized FIFO worker.
- After the terminal fence, attempts to submit more shadow mutation
  commands return false; no newer original market event or risk/rank
  mutation can advance an execution SQLite account beyond the final
  signed research checkpoint through this actor.
- The full read-only summary remains available after the fence, and
  `close` can still complete. A second terminal checkpoint is rejected.
  Existing ordinary nonterminal `checkpoint` stays reusable for tests
  and deliberately nonterminal use.
- The terminal admission fence uses a short independent threading lock
  around queue insertion and fence transition; no change to the active
  PAPER record pump, journal, fees, funding, orders or startup/restore.
  The original frozen v5 and v2 gaps remain negative.

This does **not** guarantee multi-file cross-database transactional
atomicity in crashes or ensure a complete original market stream.
Terminal archive/source parity must still be verified independently before
claiming research readiness or dollars of maker/IOC uplift.

## Acceptance

Require both exact PR head full test and research CI, post-merge CI and
independent PAPER rescue. Then wait for an actual **new** research
campaign justified by a separate root cause and a naturally adopting
worker. Do not wipe/reset the failed frozen v5 or v2 portfolios.
This is a future integrity guard, not an actual profit improvement.

Current ordinary PAPER account is still $9,769.83 marked from $10,000,
about -$230.17 after costs, 307 completed trades, original v3 source FAILED.
**NO VERIFIED PROFITABLE EDGE. LIVE OFF.**
