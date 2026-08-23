# Phase 3 WebSocket Collector and Durable Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reliable public-mainnet WebSocket ingestion layer that reconnects safely, tracks freshness, normalizes public market events, records trustworthy raw/normalized data durably, and manages a dynamic deep-watchlist without introducing trading/account mutation capability.

**Architecture:** Use `websockets` 17.x with the modern asyncio client behind an injectable connection/transport boundary so deterministic tests never require the internet. One supervisor owns connection lifecycle, subscriptions, heartbeat, reconnect, and resubscription. Parsing/normalization stays pure and independent from network I/O. A recorder receives versioned event envelopes and writes bounded rotating JSONL first for the operational slice; Parquet export/rotation is introduced in the recorder task once schema contracts are stable. The deep-watchlist manager computes subscription deltas and never exceeds configured/Hyperliquid limits.

**Tech Stack:** Python 3.12, `websockets>=17,<18`, asyncio, dataclasses, Decimal, pathlib, JSONL, optional PyArrow/Parquet only if justified in the recorder task, pytest, Ruff, mypy.

**Spec:** `docs/MASTER_SPEC.md` and `docs/BUILD_ORDER.md` Phase 3.

## Global Constraints

- Hyperliquid testnet is forbidden.
- Mainnet WebSocket endpoint is exactly `wss://api.hyperliquid.xyz/ws`.
- Phase 3 is public market-data only: `allMids`, `candle`, `l2Book`, `trades`.
- No user-specific subscriptions, wallet code, signing, orders, transfers, withdrawals, strategy logic, ML, risk decisions, or execution code.
- Default execution mode remains `paper`.
- Current documented WebSocket limits: max 10 connections/IP, 30 new connections/minute, 1000 subscriptions/IP, 2000 client-sent messages/minute.
- Server may disconnect periodically; reconnect/resubscribe is mandatory.
- Server closes a connection if it has sent no message for 60 seconds; application heartbeat uses `{"method":"ping"}` and expects `{"channel":"pong"}`.
- Every persisted event preserves source, canonical market identity where applicable, exchange timestamp where available, receive timestamp, schema version, raw/normalized provenance, and sequence/dedup metadata where available.
- Missing/stale data is represented explicitly as a gap/health event; never fabricate missing order books or trades.
- Use TDD for each task and commit coherent slices.

---

## File map

Create/modify these focused modules:

- `pyproject.toml` — add the WebSocket runtime dependency only.
- `src/cocomelon/domain/stream.py` — immutable stream/event/gap/freshness contracts.
- `src/cocomelon/hyperliquid/ws_protocol.py` — pure subscription builders, identifiers, message classification, public-event normalization.
- `src/cocomelon/hyperliquid/ws_client.py` — asyncio connection/session abstraction and send/receive primitives.
- `src/cocomelon/hyperliquid/ws_supervisor.py` — reconnect, heartbeat, resubscribe, freshness, dispatch, gap emission.
- `src/cocomelon/hyperliquid/watchlist.py` — desired-vs-active deep subscription reconciliation.
- `src/cocomelon/recorder.py` — durable rotating event writer and gap writer.
- `src/cocomelon/cli.py` — read-only `stream-smoke` operator command with bounded duration/markets and no trading capability.
- `tests/test_stream_domain.py` — stream contracts.
- `tests/test_ws_protocol.py` — protocol/normalization fixtures.
- `tests/test_ws_client.py` — injected fake connection behavior.
- `tests/test_ws_supervisor.py` — reconnect/heartbeat/resubscribe/freshness/gap behavior.
- `tests/test_watchlist.py` — subscription-delta and limit behavior.
- `tests/test_recorder.py` — durable rotation/recovery/provenance behavior.
- `tests/test_stream_cli.py` — bounded read-only CLI behavior.
- `tests/fixtures/hyperliquid_ws/` — frozen public-mainnet WebSocket fixtures captured only after read-only smoke verification.
- `scripts/capture_phase3_ws_fixtures.py` — bounded read-only fixture capture helper.

---

### Task 1: Dependency and stream domain contracts

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cocomelon/domain/stream.py`
- Create: `tests/test_stream_domain.py`

**Interfaces:**
- Produces `StreamKind`, `StreamEvent`, `DataGap`, `StreamHealth`, `FreshnessState`.

- [ ] **Step 1: Write failing domain tests**

Tests must prove:

```python
from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, FreshnessState, StreamEvent, StreamKind


def test_stream_event_preserves_provenance_and_times():
    event = StreamEvent(
        kind=StreamKind.TRADE,
        market=MarketId(dex="", coin="BTC"),
        exchange_time_ms=1_787_500_000_000,
        receive_time=datetime(2026, 8, 23, tzinfo=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="BTC:trade:123",
        payload={"price": Decimal("100")},
    )
    assert event.source == "hyperliquid-mainnet-ws"
    assert event.payload["price"] == Decimal("100")


def test_gap_requires_non_negative_duration():
    try:
        DataGap(
            stream_id="trades:BTC",
            started_ms=20,
            ended_ms=10,
            reason="disconnect",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_freshness_state_can_be_stale_without_inventing_data():
    state = FreshnessState(stream_id="l2Book:BTC", last_message_ms=1000, stale_after_ms=5000)
    assert state.is_stale(now_ms=7000) is True
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_stream_domain.py -q`

Expected: import/module failures.

- [ ] **Step 3: Add `websockets` runtime dependency and minimal immutable contracts**

Add `websockets>=17.0.1,<18` to runtime dependencies. Implement frozen dataclasses/enums with explicit validation and no network behavior.

- [ ] **Step 4: Run targeted + existing domain tests**

Run:

```bash
python -m pytest tests/test_stream_domain.py tests/test_domain.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

`feat: add stream domain contracts`

---

### Task 2: Pure Hyperliquid WebSocket protocol layer

**Files:**
- Create: `src/cocomelon/hyperliquid/ws_protocol.py`
- Create: `tests/test_ws_protocol.py`

**Interfaces:**
- Consumes `MarketId`, `StreamEvent`, `StreamKind`.
- Produces `subscription_id(subscription) -> str`, `subscribe_message(subscription) -> dict[str, object]`, `unsubscribe_message(subscription) -> dict[str, object]`, `normalize_ws_message(raw, receive_time) -> list[StreamEvent]`.

- [ ] **Step 1: Write failing tests for exact public subscription objects**

Cover:

```python
assert subscription_id({"type": "allMids", "dex": "xyz"}) == "allMids:xyz"
assert subscription_id({"type": "l2Book", "coin": "xyz:NVDA"}) == "l2Book:xyz:NVDA"
assert subscription_id({"type": "trades", "coin": "BTC"}) == "trades:BTC"
assert subscription_id({"type": "candle", "coin": "BTC", "interval": "15m"}) == "candle:BTC:15m"
```

And prove subscribe/unsubscribe messages preserve the exact original subscription object.

- [ ] **Step 2: Run targeted test and verify RED**

- [ ] **Step 3: Implement public-only protocol validation**

Reject unsupported/user-specific subscription types in this phase. Normalize:

- `subscriptionResponse` as control acknowledgement, not a market event;
- `pong` as control heartbeat, not a market event;
- `allMids` into one event per market with Decimal mid;
- `l2Book` into a full snapshot event with Decimal price/size and level order count;
- `trades` into one event per trade, with unique key based on exchange time + coin + `tid` as documented;
- `candle` into a typed normalized candle event.

HIP-3 wire coins must reuse `MarketId.from_wire_name` from Phase 2.

- [ ] **Step 4: Add malformed/out-of-order fixture tests**

Reject wrong shapes and non-finite/non-decimal numeric strings; never silently relabel a coin.

- [ ] **Step 5: Run tests**

`python -m pytest tests/test_ws_protocol.py tests/test_hyperliquid_normalize.py -q`

- [ ] **Step 6: Commit**

`feat: normalize Hyperliquid websocket messages`

---

### Task 3: Injectable asyncio WebSocket session

**Files:**
- Create: `src/cocomelon/hyperliquid/ws_client.py`
- Create: `tests/test_ws_client.py`

**Interfaces:**
- Produces an `WsConnection` protocol with async `send_json`, `recv_json`, `close` and a `connect_mainnet_ws(settings)` adapter.

- [ ] **Step 1: Write failing tests with a fake socket**

Prove JSON serialization/deserialization, canonical mainnet URL enforcement, and explicit errors for invalid JSON/binary messages.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement modern `websockets.asyncio.client.connect` adapter**

Do not enable the library's protocol-level ping as a substitute for Hyperliquid's application heartbeat. Keep connection creation injectable.

- [ ] **Step 4: Run targeted tests**

- [ ] **Step 5: Commit**

`feat: add mainnet websocket session adapter`

---

### Task 4: Supervisor — reconnect, heartbeat, resubscribe, freshness, gaps

**Files:**
- Create: `src/cocomelon/hyperliquid/ws_supervisor.py`
- Create: `tests/test_ws_supervisor.py`

**Interfaces:**
- Consumes connection factory, desired subscriptions, clock/sleep injections, event sink, gap sink.
- Produces `WebSocketSupervisor.run()` and explicit health snapshots.

- [ ] **Step 1: Write failing reconnect/resubscribe tests**

Fake sequence:

1. connection opens;
2. subscriptions are sent;
3. data arrives;
4. connection raises disconnect;
5. gap starts;
6. backoff elapses via fake sleep;
7. second connection opens;
8. all desired subscriptions replay exactly once;
9. first new message closes the gap record.

- [ ] **Step 2: Write heartbeat/freshness tests**

When no server message arrives before the configured heartbeat threshold, send `{"method":"ping"}`. Receiving `pong` updates connection liveness but does not create market data. Individual stream freshness is tracked independently.

- [ ] **Step 3: Implement bounded exponential backoff**

Initial schedule: 1s, 2s, 4s, 8s, capped at 30s; injectable for deterministic tests. Do not retry fatal configuration/protocol errors indefinitely.

- [ ] **Step 4: Implement dedup/out-of-order policy**

Maintain a bounded recent-event-key cache per stream. Duplicate exact event keys are dropped with counters. For streams where exchange timestamps go backwards, record an anomaly/gap-health event rather than reordering history silently. `l2Book` updates are snapshots, so later snapshots replace earlier state; they are not merged as deltas.

- [ ] **Step 5: Run supervisor tests**

- [ ] **Step 6: Commit**

`feat: supervise websocket reconnect and freshness`

---

### Task 5: Dynamic deep-watchlist subscription manager

**Files:**
- Create: `src/cocomelon/hyperliquid/watchlist.py`
- Create: `tests/test_watchlist.py`

**Interfaces:**
- Produces `SubscriptionPlan` and `DeepWatchlistManager.reconcile(markets)`.

- [ ] **Step 1: Write failing delta tests**

For each deep-watchlist market, desired default feeds are:

- `l2Book`;
- `trades`;
- `candle` at `1m`, `5m`, `15m` initially.

Broad feeds such as `allMids` are managed separately per discovered perp DEX and must not be duplicated per market.

- [ ] **Step 2: Test limits**

A configured deep shortlist of 20 produces 100 per-market subscriptions plus broad `allMids` feeds, well below the 1000-IP limit. Reconciliation must reject any desired state that exceeds configured safety ceiling (default 800) before sending subscriptions.

- [ ] **Step 3: Implement deterministic add/remove ordering**

Unsubscribe removed markets first, then subscribe added markets. Open-position markets, when later provided by the position layer, will be pinned; Phase 3 exposes the interface but has no positions yet.

- [ ] **Step 4: Run tests and commit**

`feat: manage dynamic deep websocket watchlist`

---

### Task 6: Durable rotating recorder and explicit data gaps

**Files:**
- Create: `src/cocomelon/recorder.py`
- Create: `tests/test_recorder.py`

**Interfaces:**
- Consumes normalized `StreamEvent`/`DataGap`.
- Produces append-only partition files and a recovery manifest.

- [ ] **Step 1: Write failing durability tests**

Prove:

- append persists one JSON record per line initially;
- Decimal/datetime values serialize deterministically;
- files partition by UTC date + stream kind + canonical market;
- rotation by max bytes/records is deterministic;
- gap records are stored separately but share provenance fields;
- reopening the recorder continues with the next safe segment and does not truncate prior files;
- write failure is surfaced, never swallowed.

- [ ] **Step 2: Implement append-only JSONL operational recorder**

Use temp-file + fsync + atomic manifest replacement for metadata. Do not hold all events in memory.

- [ ] **Step 3: Add Parquet batch export boundary**

Phase 3 should define `export_partition_to_parquet(...)` only if PyArrow is added and tested. If adding PyArrow would materially bloat the free/runtime baseline, keep JSONL as the trusted raw append log and defer columnar compaction to Phase 4/8 while documenting that decision in `docs/DECISIONS.md`. Do not fake Parquet by changing extensions.

- [ ] **Step 4: Run recorder tests and commit**

`feat: record durable market stream events`

---

### Task 7: Read-only operator smoke and public-mainnet fixture capture

**Files:**
- Modify: `src/cocomelon/cli.py`
- Create: `tests/test_stream_cli.py`
- Create: `scripts/capture_phase3_ws_fixtures.py`
- Create after smoke: `tests/fixtures/hyperliquid_ws/*.json`

**Interfaces:**
- `cocomelon stream-smoke --seconds N --market BTC` is bounded and read-only.

- [ ] **Step 1: Test CLI boundary without internet**

Inject a fake supervisor and prove the command cannot accept wallet/order/live arguments and defaults to a small bounded duration.

- [ ] **Step 2: Implement fixture capture helper**

Capture only public channels for BTC plus one discovered HIP-3 sample where available. Stop after a bounded event count/time.

- [ ] **Step 3: Temporary network smoke in GitHub Actions**

Run only:

- connection to canonical mainnet WS;
- `allMids` native + one HIP-3 DEX;
- BTC `l2Book`, `trades`, `candle`;
- application ping/pong if necessary;
- bounded fixture capture.

No user/account channels and no `post` action messages.

- [ ] **Step 4: Freeze public fixtures and add contract tests**

Commit exact captured public responses, then remove the temporary network-dependent workflow before merge.

- [ ] **Step 5: Commit**

`test: anchor Hyperliquid mainnet websocket fixtures`

---

### Task 8: Phase 3 final verification and source-of-truth update

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`

- [ ] **Step 1: Run deterministic local suite**

```bash
python -m compileall -q src tests scripts
python -m pytest -q
```

- [ ] **Step 2: Open Phase 3 PR**

- [ ] **Step 3: Require Python 3.12 CI**

Required:

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

- [ ] **Step 4: Verify exit criteria**

- disconnect/reconnect/resubscribe tests pass;
- stale streams are detected;
- duplicate/out-of-order events are handled explicitly;
- events preserve exchange and receive timestamps;
- durable recording survives reopen/rotation tests;
- real public-mainnet smoke completed successfully;
- temporary network workflow removed;
- no user-specific/trading capability introduced.

- [ ] **Step 5: Update status and portable source**

Record exact branch head, CI run, smoke run, fixture provenance, test count, and Phase 4 next action.

- [ ] **Step 6: Merge with expected head SHA and verify `main`**

Then begin Phase 4 autonomously.

---

## Self-review

- Spec coverage: reconnect/resubscribe, heartbeats/freshness, duplicate/out-of-order handling, raw/normalized contracts, durable recording, gaps, and dynamic deep-watchlist management are each mapped to explicit tasks.
- Safety coverage: no user/account/order/signing/live path appears in any Phase 3 public interface.
- Limit coverage: current Hyperliquid WebSocket limits are documented and enforced with a local safety ceiling before sends.
- Data-integrity coverage: no interpolation/reconstruction of missing microstructure; gaps are first-class records.
- Placeholder scan: no TODO/TBD implementation holes are required to understand task boundaries; the Parquet choice is an explicit evidence-based branch with a documented fallback rather than fake output.
- Type consistency: protocol identifiers, `MarketId`, `StreamEvent`, and supervisor/watchlist interfaces are defined before downstream use.
