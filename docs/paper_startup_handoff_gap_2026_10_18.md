# Next profitability-source bottleneck: PAPER first-heartbeat gap (October 18)

An authenticated original PAPER worker #39103876679 exited nonzero (143).
Its normal successor #39120486505 was dispatched at 10:45 UTC.
The authenticated GitHub Actions job step chronology was:

- Install runtime completed at **10:45:24 UTC**.
- Restore exact predecessor state: **10:45:24–10:46:22 UTC**, success.
- Restore candidate / cohort anchor completed at **10:46:26 UTC**.
- Run continuous paper trader step began **10:46:26 UTC**.
- The successor's first issue #469 authenticated PAPER heartbeat was
  **11:15:40 UTC**.

Thus the **approximately 29-minute delay after Python trader step start**
cannot be attributed merely to downloading the 2.67 GB artifact; the
workflow's own original restore phase lasted 58 seconds. The delay
includes process initialization, first upstream-data acquisition,
market seed, and any await before first published heartbeat. We cannot
identify one cause without the already measured per-component timings.

The Cocomelon runtime already calculates exact startup component durations
and puts them in the structured operational heartbeat under
`startup_component_ms`. The Issue #469 renderer omitted this data,
which obscured slow startup while source gaps and missed paper observation
became difficult to attribute.

The new bounded renderer publishes the genuine **pre-monitor total** and
five slowest named startup components, sorted deterministically. It
accepts only anonymous ASCII identifier keys and finite nonnegative
integer milliseconds with a strict maximum, never raw market names,
private paths, event keys, unknown payload objects or sensitive text.
It does not change startup, timers, database restore, risk, fees, source
feed, execution or the core PAPER account; it merely exposes real
already-recorded timings during an ordinary heartbeat.

The current worker original-v3 source failed AGAIN by 11:16 UTC:
15,241 original rows offered, 1,421 written, 13,820 dropped, even
though PAPER continued with $9,774.67 marked account equity and
288 cumulative closed trades. The recorded source will never be used
to claim 72-hour post-cost edge. Once the new renderer is running at
the next **natural** handoff, use the observed top slow startup
component to implement one safe, tested performance repair. Do not
stop the current PAPER worker or infer that a status refresh made money.

**Return authority:** no verified absolute-positive forward PAPER edge;
no risk or strategy promotion; LIVE remains disabled.
