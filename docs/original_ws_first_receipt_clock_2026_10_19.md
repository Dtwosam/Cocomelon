# October 19 — retain actual WebSocket packet receipt clocks into PAPER source

## Why this affects the profit experiment

The ordinary continuous PAPER worker remains negative after actual fees.
The strict original 72-hour v3 source also remains permanently FAILED;
at 2026-10-19 14:45 UTC it had 1,813,793 original drops and 73,349
receive-clock regressions. Repairing source coverage is required before
trusting a maker-vs-IOC profitability comparison.

A concrete WS source-timing defect was found in `WebSocketSupervisor._session`:
after successful `recv_json`, the supervisor sampled a packet millisecond
clock for liveness, but `_dispatch` independently resampled its own
millisecond clock and an UTC clock during normalization. A delay, blocking
hook, or a slow handoff between original receipt and normalization could
make a historically received packet appear later than it truly arrived.

## Source-faithful bounded change

- Freeze BOTH existing independent clocks immediately after successful
  `recv_json` and pass both unchanged into `_dispatch`.
- Use the original UTC reading to normalize ALL siblings in one WS packet,
  including every `allMids` child. Use the companion original millisecond
  liveness clock for normal supervisor accounting.
- Keep direct offline/test `_dispatch(raw)` behavior unchanged, preserving
  caller-supplied clock facilities and all source-gap commit semantics.
- Tests simulate a 5-second normalization delay after socket receipt:
  source event time, every `allMids` child, and supervisor accepted stream
  clocks must retain the actual original 2-second receive reading. A direct
  dispatch test separately asserts source exchange time is never rewritten.

**Limits:** No source row is sorted, dropped, relabeled or given a replacement
exchange clock. A downstream gap accepted later still has its true PAPER
serialization receipt and may legitimately make original chronological
admission fail. There is no assertion that the known gap/scheduling regression
has been repaired or that a 72-hour source is now complete. This has no effect
on the currently running older worker until a normal future handoff.

Trading policy, fee schedule, account valuation, execution, risk, position
stops, original strict source verdict, worker restart and LIVE trading are
unchanged. **NO PROFITABLE EDGE VERIFIED. LIVE DISABLED.**
