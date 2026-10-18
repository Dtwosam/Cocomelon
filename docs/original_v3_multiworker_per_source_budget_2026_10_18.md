# October 18 — real original-v3 source row and byte budget per PAPER worker

## Verified economic testing constraint

The frozen LONG-trend challenger must compete against an unchanged PAPER
baseline using **72+ hours of original continuous market source**, two
independent matched-capital accounts and positive **absolute** after-cost
whole-account PnL. The ordinary PAPER trader rolls over roughly every
**four hours**; a merged offline multiworker evaluator (PR #1342)
can combine distinct authentic consecutive archives without rewriting
source timestamps or dropping original rows.

At authenticated Issue #469, **2026-10-18 11:43 UTC**, the current worker
had offered **394,740** original rows, durably written only **1,421**,
and lost **393,319**, with confirmed original receive-clock regressions
and actual source gaps. The observed-volume-only 72-hour projection
was about **59 million rows**, far above a *single worker*'s 5 million
row source cap. That was misleading if interpreted as proof that
multiworker 72h source would never fit: roughly 18 separate four-hour
archives are needed; the merged multiworker evaluator has a separately
bounded **100 million row total**.

### Source capacity requires TWO distinct budgets

At the actual offered row rate, after at least ten minutes of original
timestamps, retain the older hypothetical 72-hour row count for
comparison but calculate these **separate conditional** values:

- The expected **4h per-worker rows** versus **5 million per-worker
  original JSONL records**. No one may apply this bound to the total
  72-hour chain.
- The expected **4h per-worker UNCOMPRESSED journal bytes** versus
  the existing **480 MiB per-worker original journal limit**, estimated
  using *already durably written byte count / durably written row count*.
  This sample is inevitably biased if the source failed early and is
  never a source certificate. Lack of written rows returns *unknown*,
  not "fits".
- The expected **72h multiworker rows** versus the current **100
  million row bounded replay work ceiling**. Eighteen is the *minimum
  nominal number* of natural four-hour workers; handoff gaps and
  short/overlapping/invalid sources still reject the entire trial.

This gives the research team a falsifiable next question: even if
approximately 59 million original rows could be distributed over
18 workers under their **row caps**, can each uncompressed original
archive fit its *separate byte limit* without source thinning,
timestamps modified, event omissions or forged gaps? If not, only a
future independently validated **lossless encoding / original
source writer** design with corresponding pinned replay reader could
solve storage; fee, source, risk or strategy standards may not be
relaxed to force the result.

The projection never certifies 72h completeness or exchange-clock
integrity; never turns early-failed recorder segments into evidence;
never recomputes past market records; never changes original event
timestamps or receive order, source limits, PAPER strategy, open
positions, fees, funding, risk, execution or LIVE authority. Old and
current failed v3 archives remain **permanently invalid**.

### Test contract

Unit cases explicitly cover high row rates that **fail a one-file
72h budget but fit 4h workers**, byte samples that independently fail
480 MiB, missing sample bytes reported unknown, per-worker and 100M
chain row overflow, and source-integrity failure that never becomes
qualified. The test synchronizes multiworker replay's 100M source
work ceiling and keeps the original 72h diagnostics for compatibility.

**Zero demonstrated positive net trading edge remains the default.
LIVE stays disabled.**
