# Hosted per-block full-depth L2 diagnostic (read-only)

Status: **research-only**. This probe is **not** part of continuous paper
trading, execution, account checkpoints, market gap repair, or risk control.

## October 14 baseline

Independent [public 20-depth sample](https://github.com/Dtwosam/Cocomelon/actions/runs/38622404124):
700 SHA-256-verified receipts, 35 per market across 20 markets. Median
distinct-book interarrival 5.365 seconds; available source time under 3
seconds about 46–48%. These data do not support relaxing freshness rules.

## Optional hosted gRPC candidate

QuickNode documents the TLS method
hyperliquid.OrderBookStreaming/StreamL2Book, requested 20 depth levels,
complete book per block and x-token auth header. The adapter dynamically
constructs the vendor's documented protobuf wire message subset.

Public specs:
https://github.com/quiknode-labs/hypercore-grpc-examples/blob/main/docs/orderbook-streaming.md
https://raw.githubusercontent.com/quiknode-labs/hypercore-grpc-examples/main/proto/orderbook.proto

A separately provisioned endpoint and credential are **required**. None
are present in code or outputs. No subscription is free of provider
conditions, and running this does not require or permit real-money trading.

Local command with provider credentials that you control:

    python -m pip install -e .
    python -m pip install "grpcio>=1.67,<2" "protobuf>=5,<7"
    export GRPC_ENDPOINT=your-endpoint.hype-mainnet.quiknode.pro:10000
    export AUTH_TOKEN=<provider token>
    python -m cocomelon.research.block_l2_grpc_probe \
      --duration-seconds 180 --out-dir grpc-l2-diagnostic

Alternatively add repository Actions secrets named
QUICKNODE_HYPERCORE_GRPC_ENDPOINT and QUICKNODE_HYPERCORE_GRPC_TOKEN, then
dispatch the manual workflow "Optional QuickNode Full-Depth gRPC Diagnostics".
The endpoint must be a bare QuickNode mainnet hostname on port 10000,
with TLS. Do not place credentials in issues, PRs, logs or commits.

## Strict diagnostic rules

- Each market must have at least 20 bids and 20 asks to count as depth
  eligible. Fewer levels never become 20-depth proof.
- Timestamp-age limits remain 3000ms and 5000ms. Duplicate, regressing,
  future-dated, malformed and crossed books never refresh eligibility.
- Markets are restricted to the frozen 20-market public-source cohort.
- Block-height jumps are logged but never interpreted as validated venue
  completeness; source-clock offsets remain an uncertainty.
- Per-market valid freshness is integrated over monotonic **elapsed time**,
  not heartbeat snapshots. Provider receipt bytes are hashed separately.
- Empty sources, parse/stream errors, prematurely ended runs, or any market
  with fewer than two distinct books fail the observation-window verdict.

The candidate is never promoted to signed trading history, orders or the
paper account, including when it appears faster. Positive source evidence
does not imply positive after-cost strategy returns.

Further work requires vendor-source verification and an independent
forward-only PAPER shadow: exact coin/depth parity, timestamps, continuity,
price/order validation, feed-gap reconciliation and economics. LIVE remains
disabled.
