# Cocomelon Project Status

**Last updated:** 2026-08-23  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`

## Current state

**Last completed phase:** Phase 2 — Hyperliquid mainnet discovery and REST snapshots  
**Integration state:** MERGED into `main`  
**Phase 2 merge commit:** `b95352e238d6a9eabd63e13c1f8300e654a7e636`  
**Active next phase:** Phase 3 — WebSocket collector and durable market recording

## Phase 2 implementation evidence

Phase 2 established:

- a direct mainnet-only Hyperliquid `/info` HTTP client with injectable transport;
- canonical-mainnet endpoint enforcement;
- retry/backoff for 429, server, and transport failures only;
- rolling REST rate-budget protection below the documented 1,200-weight/minute ceiling;
- dynamic discovery of the native perp venue plus HIP-3/perp DEX namespaces;
- canonical HIP-3 market IDs such as `xyz:NVDA` without double-prefixing;
- typed immutable market, asset-context, candle, and funding records;
- `Decimal`-based financial normalization;
- preservation/identification of delisted markets;
- candle and funding-history fetch/normalization with timestamp/order validation;
- a read-only `cocomelon markets` operator command;
- public mainnet fixture capture tooling;
- captured real Hyperliquid mainnet public fixtures committed to the repository;
- deterministic fixture contract tests against those real captured structures.

## Real-mainnet smoke evidence

A temporary read-only GitHub Actions workflow was used only for public Hyperliquid mainnet `/info` reads, then removed before merge.

Successful smoke run:

- Workflow run: `32647847123` — SUCCESS;
- Python: `3.12.14`;
- `python -m cocomelon markets` — PASS;
- public fixture capture — PASS;
- source endpoint: `https://api.hyperliquid.xyz/info`;
- no wallet, signing, account mutation, order, or execution method was involved.

Observed market-discovery snapshot during the smoke:

- 500 discovered perpetual markets;
- 320 active markets;
- 180 delisted markets;
- 11 perp DEX namespaces total;
- 10 HIP-3/perp DEX namespaces beyond the native venue;
- sampled HIP-3 wire symbols included `xyz:XYZ100`, `xyz:TSLA`, and `xyz:NVDA`.

## Final Phase 2 verification

Final feature-tree CI after the temporary network workflow was removed:

- verified head before status-only update: `1961e0112770172cb475a574cb4ca2a26dd1627c`;
- CI run: `32648127671` — SUCCESS;
- project install — PASS;
- Ruff (`src tests scripts`) — PASS;
- mypy (`src`) — PASS;
- pytest — PASS;
- subsequent status-only commit CI run `32648418819` — SUCCESS;
- local execution-sandbox suite reached 42 passing tests, including captured real-mainnet fixture contracts.

## Phase 3 current design facts

Current official Hyperliquid documentation has been re-checked before Phase 3 planning:

- mainnet WebSocket endpoint: `wss://api.hyperliquid.xyz/ws`;
- server may disconnect periodically and clients must reconnect/resubscribe;
- missed data may appear in snapshot acknowledgements or be recovered through corresponding info requests;
- server closes a connection if it has not sent a message for 60 seconds; clients may send `{"method":"ping"}` and receive `{"channel":"pong"}`;
- public subscription types needed by Phase 3 include `allMids`, `candle`, `l2Book`, and `trades`;
- `allMids` supports an optional perp DEX namespace;
- current per-IP limits include 10 WebSocket connections, 30 new connections/minute, 1000 subscriptions, and 2000 messages sent/minute.

Phase 3 will remain public-market-data only. User/account subscriptions, signing, orders, and live execution remain out of scope.

## Safety invariants still locked

- Hyperliquid testnet is forbidden.
- Runtime data sources remain Hyperliquid mainnet only.
- Default execution mode remains `paper`.
- Live trading is disabled.
- No live exchange adapter exists.
- No strategy engine exists yet.
- No ML/learning engine exists yet.
- No wallet signing, order placement, transfer, or withdrawal capability exists.
- Risk defaults remain 0.25% per trade, 0.75% aggregate planned open risk, 1% daily loss lockout, and 3% rolling weekly drawdown lockout.
- Solidity is not part of V1.
- No secrets may be committed or emitted in logs.

## Exact next action

1. Create and commit the dedicated Phase 3 implementation plan for **WebSocket collector and durable market recording**.
2. Execute Phase 3 autonomously on an isolated feature branch using TDD.
3. Add reconnect/resubscribe, heartbeat/freshness, duplicate/out-of-order handling, event normalization, rotating durable storage, gap records, and dynamic deep-watchlist subscription management.
4. Use a read-only mainnet smoke only where network verification is necessary, then remove any temporary network-dependent CI before merge.
5. Merge only after deterministic CI and Phase 3 exit criteria pass.

Do not begin scanner/strategy, ML, paper execution, or live execution before their preceding build-order phases pass.

## Live trading status

**DISABLED.**

There is no approved live execution path yet. The project remains in market-data infrastructure stages until the later promotion gates in `docs/MASTER_SPEC.md` and `docs/BUILD_ORDER.md` are satisfied.
