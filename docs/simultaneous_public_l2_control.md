# Independent public 20-level versus fast five-level diagnostic

This is an optional, **read-only, zero-credential** comparison of two public
Hyperliquid WebSocket subscriptions for the exact 20-market PAPER cohort.

It opens two separate WebSocket connections at nearly the same instant:

- **Control A:** unmodified default public \`l2Book\` subscription, aiming
  to observe 20 bid levels and 20 ask levels.
- **Control B:** public \`l2Book\` with \`fast: true\`, aiming for only
  5 levels per side with more frequent updates.

The developer API documents the ordinary public \`l2Book\` subscription.
Hyperliquid's broader open-source ecosystem and QuickNode describe
\`fast: true\` as a *five-level* faster update feed, not as full depth:

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- https://github.com/quicknode/Hyperliquid-Orderbook-Radar

## Run

    python -m pip install -e .
    python -m cocomelon.research.simultaneous_public_l2_control \
      --duration-seconds 180 --out-dir public-depth-control

A one-time workflow of the same name automatically runs after this
module's initial merge and can later be manually dispatched.
No API key, paid provider, private endpoint, account or real-money access
is used, and there is no connection to continuous PAPER trading.

The command saves six files: full 20x20 source-receipts JSONL, deep summary,
fast-control source-receipts JSONL, control summary, comparison JSON,
and (in GitHub Actions) a condensed issue report. Original raw messages
are not archived; only per-message SHA-256 diagnostic digests, clocks
and reported level counts are stored. The reports do not prove venue
completeness, independent clock synchronization or price executability.

## Interpretation

A valid result requires the complete frozen cohort to receive >=20 unique
full-depth **20x20** books per market, and >=20 five-or-fewer-level control
snapshots per market, over a simultaneous 180+ second observation window.
Both socket connections must run without recorded reconnects, protocol
failures, out-of-order or future-dated source timestamps. Unexpected depths
or missing rows fail the diagnostic rather than silently widening eligibility.

**Never use the fast-control snapshots to fill out, synthesize, or
complete any missing full-depth level.** A fast five-level packet can
provide a control for venue update cadence; it cannot verify depth,
slippage, book shape, market source-gap continuity, trade entry/exit
eligibility or after-cost trading edge. The application intentionally
returns \`five_level_execution_authorized: false\`,
\`full_depth_source_swap_authorized: false\`,
\`live_trading_authorized: false\`, and
\`profitability_verified: false\` regardless of performance.

This new experiment is independent of the earlier, *noncontemporaneous*
QuickNode-hosted-gRPC candidate, which still requires legitimate provider
credentials and a paired 20-level prospective test. For any actual source
replacement, independent complete-source checks, untouched PAPER
risk constraints and a long prospective after-cost screen still apply.
