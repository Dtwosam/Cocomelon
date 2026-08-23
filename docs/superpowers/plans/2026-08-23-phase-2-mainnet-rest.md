# Phase 2 Mainnet REST Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably discover Hyperliquid mainnet perpetual markets across the native and HIP-3 DEX namespaces, normalize low-frequency market context, and expose safe read-only smoke commands without any trading capability.

**Architecture:** Add a dependency-light direct `/info` HTTP client with an injectable transport, conservative rolling rate-budget accounting, bounded retry/backoff, and strict mainnet-only configuration. Build typed normalizers and a market registry above that client. Use `Decimal` for financial values, preserve raw wire names/provenance/timestamps, and keep HTTP/JSON concerns separate from domain models. The official SDK remains useful later, but Phase 2 does not depend on its `metaAndAssetCtxs` wrapper because the current Python SDK still lacks a `dex` argument even though Hyperliquid's API accepts one.

**Tech Stack:** Python 3.12, stdlib `urllib.request`, `json`, `decimal`, `dataclasses`, `collections.deque`, pytest, Ruff, mypy, GitHub Actions.

**Spec:** `docs/MASTER_SPEC.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Runtime reads use `https://api.hyperliquid.xyz/info` only unless the user explicitly changes the canonical mainnet endpoint.
- Execution remains paper-only; Phase 2 contains no order placement, signing, wallet, or exchange action code.
- REST budgeting follows the current official 1,200-weight-per-minute IP limit and uses a conservative configurable working ceiling below it.
- `meta`, `metaAndAssetCtxs`, `perpDexs`, `fundingHistory`, and `candleSnapshot` are treated as heavy info calls with base weight 20; response-size surcharges are modeled for candles/funding when known.
- Market discovery is dynamic and supports native plus HIP-3 DEX namespaces.
- HIP-3 wire market names are already DEX-prefixed; canonicalization must never produce `dex:dex:COIN`.
- Financial values are parsed to `Decimal`, not binary float.
- Every normalized snapshot preserves source, receive timestamp, and schema version.
- Missing or malformed data fails explicitly; normalizers do not silently invent values.
- Tests use deterministic fixtures; a live mainnet smoke check is separate from unit tests and performs reads only.

---

## File map after Phase 2

```text
src/cocomelon/
├── cli.py
├── domain/
│   └── market.py
└── hyperliquid/
    ├── __init__.py
    ├── client.py
    ├── normalize.py
    ├── rate_limit.py
    └── registry.py
scripts/
└── capture_phase2_fixtures.py

tests/
├── fixtures/hyperliquid/
│   ├── perp_dexs.json
│   ├── meta_and_asset_ctxs_main.json
│   ├── meta_and_asset_ctxs_hip3.json
│   ├── candles_btc_15m.json
│   └── funding_btc.json
├── test_hyperliquid_client.py
├── test_hyperliquid_normalize.py
├── test_market_registry.py
└── test_phase2_cli.py
```

### Task 1: Canonical market and snapshot domain contracts

**Files:**
- Modify: `src/cocomelon/domain/market.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Produces: `MarketId.from_wire_name(dex, wire_name)`, `PerpDex`, `PerpMarketMeta`, `PerpMarketContext`, `PerpMarketSnapshot`, `Candle`, `FundingRate`.
- Later tasks consume these immutable dataclasses.

- [ ] **Step 1:** Add failing tests proving native names stay `BTC`, HIP-3 wire name `xyz:NVDA` becomes `MarketId(dex="xyz", coin="NVDA")`, mismatched prefixes fail, and financial snapshot values use `Decimal`.
- [ ] **Step 2:** Run `python -m pytest tests/test_domain.py -q` and confirm the new tests fail for missing contracts.
- [ ] **Step 3:** Implement the minimal frozen/slot dataclasses and `MarketId.from_wire_name()` canonicalization.
- [ ] **Step 4:** Re-run domain tests, Ruff, and mypy.
- [ ] **Step 5:** Commit as `feat: add perpetual market snapshot contracts`.

### Task 2: Weighted mainnet info client

**Files:**
- Create: `src/cocomelon/hyperliquid/__init__.py`
- Create: `src/cocomelon/hyperliquid/rate_limit.py`
- Create: `src/cocomelon/hyperliquid/client.py`
- Test: `tests/test_hyperliquid_client.py`

**Interfaces:**
- Produces: `RollingRateBudget.acquire(weight)`, `InfoClient.post_info(payload, weight)`, `InfoClient.perp_dexs()`, `InfoClient.meta_and_asset_ctxs(dex)`, `InfoClient.candles(...)`, `InfoClient.funding_history(...)`.
- Transport is injectable for tests and defaults to a stdlib JSON POST transport.

- [ ] **Step 1:** Write failing tests for a rolling 60-second weighted budget, testnet URL rejection inherited from `Settings`, request JSON shape, timeout, retry on 429/5xx/transport errors, and no retry on ordinary 4xx.
- [ ] **Step 2:** Run the focused tests and confirm RED for missing client/rate-limit modules.
- [ ] **Step 3:** Implement `RollingRateBudget` with injected monotonic clock/sleeper and a default working ceiling of 1,000 weight per rolling 60 seconds, leaving headroom under Hyperliquid's documented 1,200 limit.
- [ ] **Step 4:** Implement `InfoClient` with bounded exponential backoff, JSON validation, explicit request weights, and methods for Phase 2 endpoints. `meta_and_asset_ctxs` must send the supplied `dex` field directly.
- [ ] **Step 5:** Re-run focused tests, full pytest, Ruff, and mypy.
- [ ] **Step 6:** Commit as `feat: add rate-aware Hyperliquid mainnet info client`.

### Task 3: Perp DEX discovery, normalization, and market registry

**Files:**
- Create: `src/cocomelon/hyperliquid/normalize.py`
- Create: `src/cocomelon/hyperliquid/registry.py`
- Test: `tests/test_hyperliquid_normalize.py`
- Test: `tests/test_market_registry.py`

**Interfaces:**
- Produces: `normalize_perp_dexs(raw)`, `normalize_meta_and_asset_ctxs(dex, raw, received_at_ms)`, `MarketRegistry.refresh()` and immutable registry snapshots keyed by canonical market name.
- Consumes: Phase 2 domain contracts and `InfoClient`.

- [ ] **Step 1:** Add fixtures covering native metadata/context, HIP-3 prefixed wire names, a delisted market, null optional mid/mark fields, and `perpDexs[0] == null`.
- [ ] **Step 2:** Write failing normalizer tests proving positional meta/context alignment, Decimal parsing, delisted propagation, source/timestamp/schema provenance, and prefix-safe canonical keys.
- [ ] **Step 3:** Implement strict normalization. Reject malformed tuple length, missing required numeric fields, duplicate canonical markets, or HIP-3 prefix mismatch.
- [ ] **Step 4:** Write failing registry tests using an injected fake `InfoClient`; verify it queries `perpDexs`, then native plus each discovered non-null DEX, without hard-coded coins.
- [ ] **Step 5:** Implement `MarketRegistry.refresh()` and immutable lookup/list methods.
- [ ] **Step 6:** Run focused tests, full pytest, Ruff, and mypy.
- [ ] **Step 7:** Commit as `feat: discover and normalize Hyperliquid perp markets`.

### Task 4: Candle and funding snapshots

**Files:**
- Modify: `src/cocomelon/hyperliquid/client.py`
- Modify: `src/cocomelon/hyperliquid/normalize.py`
- Test: `tests/test_hyperliquid_normalize.py`

**Interfaces:**
- Produces normalized `tuple[Candle, ...]` and `tuple[FundingRate, ...]`.

- [ ] **Step 1:** Write failing tests for candle OHLCV/trade-count parsing, interval/coin preservation, ascending timestamp order, funding-rate/premium parsing, and malformed timestamps.
- [ ] **Step 2:** Implement `normalize_candles()` and `normalize_funding_history()` with `Decimal` prices/size/rates.
- [ ] **Step 3:** Ensure client request builders use canonical wire market names (`BTC` or `xyz:NVDA`) and accept explicit time windows.
- [ ] **Step 4:** Model documented response-size weight surcharges conservatively from the requested candle count/time window and funding page size assumptions so the client cannot poll these endpoints as if they were cheap calls.
- [ ] **Step 5:** Run focused tests, full pytest, Ruff, and mypy.
- [ ] **Step 6:** Commit as `feat: normalize candle and funding snapshots`.

### Task 5: Read-only operator smoke and reproducible mainnet fixtures

**Files:**
- Modify: `src/cocomelon/cli.py`
- Create: `scripts/capture_phase2_fixtures.py`
- Create/refresh: `tests/fixtures/hyperliquid/*.json`
- Test: `tests/test_phase2_cli.py`
- Modify: `.github/workflows/ci.yml` only if needed for deterministic checks; live network smoke must not become a flaky unit-test dependency.

**Interfaces:**
- Produces: `cocomelon markets` read-only summary and fixture-capture script.

- [ ] **Step 1:** Write failing CLI tests proving `cocomelon markets` uses `Settings.from_env()`, never exposes secrets, and prints market counts/DEX counts/delisted counts with no trading side effects.
- [ ] **Step 2:** Implement the CLI command and capture script. Capture script writes only public `/info` responses and rejects non-mainnet configuration.
- [ ] **Step 3:** Run deterministic tests locally/CI.
- [ ] **Step 4:** Run the capture/smoke script against real Hyperliquid mainnet from a networked CI environment, inspect the public output, and commit sanitized raw fixtures for `perpDexs`, native `metaAndAssetCtxs`, one HIP-3 `metaAndAssetCtxs` response when available, BTC candles, and BTC funding. No user/account endpoints are queried.
- [ ] **Step 5:** Re-run contract tests against the captured fixtures. If current schema differs from assumptions, adjust normalizers/tests based on the observed public schema rather than coercing the fixture.
- [ ] **Step 6:** Commit as `test: anchor Hyperliquid mainnet REST fixtures`.

### Task 6: Phase 2 verification and handoff

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Create: `docs/superpowers/plans/2026-08-23-phase-3-websocket-recorder.md` only after Phase 2 is verified, or leave Phase 3 planning as the exact next action if the plan has not yet been written.

- [ ] **Step 1:** Run `python -m pip install -e ".[dev]"`.
- [ ] **Step 2:** Run `python -m ruff check src tests scripts`.
- [ ] **Step 3:** Run `python -m mypy src`.
- [ ] **Step 4:** Run `python -m pytest -q`.
- [ ] **Step 5:** Run a read-only mainnet smoke command and verify it discovers a dynamic native/HIP-3 universe without any order/trading action.
- [ ] **Step 6:** Verify testnet URLs remain rejected, execution mode remains paper, and no wallet/signing/live order modules were introduced.
- [ ] **Step 7:** Update `docs/STATUS.md` and `docs/CHATGPT_PROJECT_SOURCE.md` with exact commits, CI run, live-smoke evidence, Phase 2 completion, and Phase 3 as the next phase.
- [ ] **Step 8:** Open PR, require CI green, merge to `main`, and verify the merge commit.

## Phase 2 self-review checklist

- [ ] Dynamic native + HIP-3 discovery; no favorite-token hard-coding.
- [ ] HIP-3 canonical names cannot double-prefix.
- [ ] `metaAndAssetCtxs` is queried with explicit `dex` for HIP-3.
- [ ] Decimal parsing is used for financial values.
- [ ] Schema/provenance/receive timestamps are preserved.
- [ ] Delisted status is represented rather than silently dropped.
- [ ] Rate-budget code is deterministic and tested.
- [ ] Retry logic is bounded and does not retry arbitrary 4xx responses.
- [ ] Candle/funding expensive-response weights are accounted for conservatively.
- [ ] Raw public mainnet fixture provenance is recorded.
- [ ] Unit tests do not require internet.
- [ ] Live smoke is read-only and separate from deterministic CI tests.
- [ ] No strategy, ML, paper execution, wallet, signing, or live order code is introduced.
