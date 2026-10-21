# Frozen temporary pressure / visible recovery exploratory policy

See [full strategy and trial](../../../docs/exploratory_flow_exhaustion_2026_10_21.md),
[protocol](protocol.json), [pre-outcome clarification](freeze-clarification.json),
[economic lessons](economic-lessons.md), [authenticated aggregate snapshot](evidence-snapshot.json).

Status: prepared policy; NOT ACTIVATED; zero prospective observations/results.
Synthetic tests are logic checks, not trading evidence. Existing worker, controls,
accounts, failures, PR1392 and live-disabled boundaries remain unchanged.

Official references rechecked2026-10-21:

- [Hyperliquid WebSocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions): native trade and L2 fields; books are snapshots rather than an order-by-order queue. Native trade identity includes coin, block timestamp and tid.
- [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees): native base tier taker0.045% per fill; no rebates/discount assumed.
- [Hyperliquid rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits): per-IP aggregate limits; another in-process budget is not an independent IP-wide certificate.

Existing normalized trades map B/A as buy/sell in strategies/microstructure.py and
hyperliquid/ws_protocol.py. A future launcher must independently attest native
side semantics/source clocks and complete original tape/book coverage before using
this input; string fields alone are not source authentication. No external market
observations or outcomes were acquired for this new hypothesis during preparation.
