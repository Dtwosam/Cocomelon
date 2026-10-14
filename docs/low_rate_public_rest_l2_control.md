# Low-rate public REST full-depth market-data diagnostic

This is an isolated, forward-only read-only experiment to determine whether
Hyperliquid's public REST \`POST /info {"type":"l2Book","coin":"..."}\`
returns truly newer **20-level** books than its default L2 WebSocket.

The earlier simultaneous 20-market public websocket comparison yielded:
- 700 public 20x20 unique books, median delivery gap 5.36553 seconds
- 6,560 public 5x5 fast-control books, median delivery gap 0.54482 seconds
- Fast data cannot supply full-depth liquidity and is NEVER an execution feed.

The official Hyperliquid Info API documents that the L2 REST response has
**up to 20 levels per side**. The official rate-limit guidance assigns
\`l2Book\` **weight 2** and permits **1,200 REST weight/minute per IP**:

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits

## Exact bounded experiment

The probe concurrently measures the *same* three original PAPER markets
(\`BLUR\`, \`BOME\`, \`CASHCAT\`) for 180 seconds. It opens one default public
20-depth WebSocket and polls the read-only public REST endpoint **no more
than once per second per coin**. At most **3 requests/second**,
**180 requests/minute**, or **360 API weight/minute** can be created by
this experiment. Skipped/delayed polls are never burst-retried, and 429
responses fail the diagnostic.

Local command (no account, API keys, provider payments or order rights):

    python -m pip install -e .
    python -m cocomelon.research.low_rate_rest_l2_control \
      --duration-seconds 180 \
      --out-dir public-rest-full-depth

An initial merge into main triggers one bounded diagnostic run; thereafter
the separate GitHub Actions workflow can be manually dispatched. No
perpetual polling or background REST traffic is configured.

## How to read results

Source updates are only counted as **unique** if they have genuinely
different exchange-time + book identity. Polling the same cached 20-level
book twenty times **never** converts it into twenty fresh market books.
Missing, stale-on-arrival, future-dated or shallow snapshots do not inflate
the 3-second source freshness fraction. When a market has fewer than
20 bids or 20 asks, its responses are observed but cannot prove 20x20 depth.

The resulting artifact keeps source message SHA-256 receipts and raw
timestamps, reported observed 20-level depth, same-window WebSocket
receipts, HTTP request/error count, and source-age duty cycle for each
of three markets. A valid experiment requires error-free bounded REST
calls, complete 180+ second runs on both transports, full 20-by-20
depth at every unique accepted observation and no future/out-of-order
source events. If this cannot be met, the experiment fails closed.

**A diagnostic pass is NEVER authorization to use REST for production
execution.** Even if REST performs better on three markets, multiplying
this poll rate to all twenty markets would exceed the current REST API
weight limit before accounting for other worker requests. HTTP network
latency, shared per-IP limits, sample size, source completeness, signed
gap history, independent account audits and positive after-cost economic
evidence must all be addressed before any production source replacement.
The running PAPER worker remains untouched; LIVE stays disabled.
