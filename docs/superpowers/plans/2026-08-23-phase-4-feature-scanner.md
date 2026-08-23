# Phase 4 Feature Engine and Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn trustworthy Phase 2/3 Hyperliquid observations into deterministic, lookahead-safe feature snapshots, eligibility decisions, direction-neutral opportunity ranks, and a bounded dynamic deep-watchlist shortlist.

**Architecture:** Phase 4 keeps the approved three-tier funnel. Broad context features and coarse eligibility run across every dynamically discovered perp market; candle enrichment runs only on high-ranked candidates; L2 spread/depth becomes a deep-readiness gate after a market is subscribed for deep data. The opportunity ranker is explicitly direction-neutral and cannot authorize trades; Phase 5 remains responsible for LONG/SHORT/NO_TRADE decisions.

**Tech Stack:** Python 3.12, stdlib `dataclasses`/`Decimal`/`enum`/`hashlib`, existing Phase 2 market/candle contracts, existing Phase 3 `StreamEvent` and `DeepWatchlistManager`, pytest, Ruff, mypy. Do not add NumPy/Polars/PyArrow to the always-on scanner unless a measured need appears later.

**Spec:** `docs/MASTER_SPEC.md` sections 3.4, 4.1, and 5, plus `docs/BUILD_ORDER.md` Phase 4 and locked decisions D-001, D-005, D-009, D-010, D-012, D-013, D-020, D-021.

## Global Constraints

- Hyperliquid testnet is forbidden; runtime observations are mainnet only.
- Phase 4 does not place orders, sign messages, read user/account streams, size positions, emit LONG/SHORT decisions, or introduce ML control.
- Market discovery remains dynamic; do not hard-code a favorites universe.
- Eligibility and ranking are separate: eligibility answers whether a market can responsibly proceed; ranking answers whether current activity deserves scarce analysis capacity.
- A market may be rankable from Tier A data before it is deep-ready. Future strategies must consume only markets that have passed the deep-readiness gate.
- Never require L2 for the entire universe. L2/trades remain bounded Tier C data.
- Feature calculations must use observations with receipt/exchange times at or before `as_of_ms`; future candles are ignored and future-received inputs fail closed.
- All financial arithmetic exposed in domain snapshots uses `Decimal`; no feature score is called a probability.
- Feature snapshots carry schema version, deterministic snapshot id, provenance, market identity, and `as_of_ms`.
- Existing risk defaults and live-mode gates are unchanged. Live trading remains disabled.
- No fabricated historical L2 or trade flow is permitted.

---

### Task 1: Versioned Phase 4 domain contracts

**Files:**
- Create: `src/cocomelon/domain/features.py`
- Create: `tests/test_feature_domain.py`

**Interfaces:**
- Consumes: `MarketId` from `cocomelon.domain.market`.
- Produces: `TrendRegime`, `VolatilityRegime`, `FeatureSnapshot`, `EligibilityDecision`, `ScoreComponent`, `OpportunityRank`, `ShortlistDelta`, and `ScanResult`.

- [ ] **Step 1: Write failing contract tests**

Cover timezone-independent integer `as_of_ms`, non-negative ages, score bounds `[0, 1]`, rank ordinals `>= 1`, canonical market identity, immutable reason/provenance tuples, deterministic `snapshot_id`, and invalid negative timestamps.

Representative test shape:

```python
from decimal import Decimal

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId


def test_feature_snapshot_identity_is_deterministic() -> None:
    kwargs = dict(
        market=MarketId("", "BTC"),
        as_of_ms=1_000,
        source_received_at_ms=900,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UNKNOWN,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=("hyperliquid-mainnet-info",),
    )
    assert FeatureSnapshot(**kwargs).snapshot_id == FeatureSnapshot(**kwargs).snapshot_id
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/test_feature_domain.py -q
```

Expected: FAIL because `cocomelon.domain.features` does not exist.

- [ ] **Step 3: Implement minimal immutable contracts**

Use `@dataclass(frozen=True, slots=True)`. `FeatureSnapshot.snapshot_id` is computed from a canonical string containing schema version, canonical market, `as_of_ms`, all numeric/enum feature fields, and sorted provenance, then SHA-256 truncated to 24 hex characters. Do not use Python's process-randomized `hash()`.

Required enums:

```python
class TrendRegime(StrEnum):
    UP = "up"
    DOWN = "down"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class VolatilityRegime(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNKNOWN = "unknown"
```

`EligibilityDecision` contains:

```python
market: MarketId
rankable: bool
deep_ready: bool
reasons: tuple[str, ...]
```

`ScoreComponent` contains `name`, `raw_value`, `percentile`, `weight`, and `contribution`, each numeric field as `Decimal` and bounded where appropriate. `OpportunityRank` contains market, ordinal, score, components, and reason codes. `ShortlistDelta` contains `added`, `removed`, and `current` as canonical `MarketId` tuples. `ScanResult` contains feature snapshots, eligibility decisions, ranks, Tier B candidates, shortlist delta, and the resulting Phase 3 `SubscriptionPlan` only through a loose object/protocol boundary to avoid circular domain imports.

- [ ] **Step 4: Run GREEN and static checks**

```bash
python -m pytest tests/test_feature_domain.py -q
python -m ruff check src/cocomelon/domain/features.py tests/test_feature_domain.py
python -m mypy src/cocomelon/domain/features.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cocomelon/domain/features.py tests/test_feature_domain.py
git commit -m "feat: add versioned market feature contracts"
```

---

### Task 2: Deterministic broad-market features and cross-sectional math

**Files:**
- Create: `src/cocomelon/features/__init__.py`
- Create: `src/cocomelon/features/math.py`
- Create: `src/cocomelon/features/broad.py`
- Create: `tests/test_broad_features.py`
- Create: `tests/test_feature_math.py`

**Interfaces:**
- Consumes: `PerpMarketSnapshot`, optional prior `PerpMarketSnapshot`, and `as_of_ms`.
- Produces: deterministic quantile/percentile helpers and `BroadFeatureValues` used by the feature assembler.

- [ ] **Step 1: Write RED tests for quantiles and broad features**

Prove:

- percentile/quantile output is deterministic under reordered input;
- equal values receive equal percentile scores;
- empty input raises a clear `ValueError` when a threshold cannot be derived;
- current context with `received_at_ms > as_of_ms` is rejected as lookahead;
- `day_return = reference_price / prev_day_px - 1`, where reference price prefers `mid_px`, then `mark_px`;
- OI change is `(current_oi / previous_oi) - 1` only when a same-market prior snapshot with positive OI exists;
- funding change is current minus previous funding;
- mark/oracle dislocation in bps is absolute and uses oracle as denominator;
- no float conversion occurs.

Representative formulas:

```python
assert broad.day_return == Decimal("101") / Decimal("100") - Decimal("1")
assert broad.oi_change_fraction == Decimal("120") / Decimal("100") - Decimal("1")
```

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_feature_math.py tests/test_broad_features.py -q
```

Expected: FAIL because feature modules do not exist.

- [ ] **Step 3: Implement Decimal helpers**

`percentile_rank(values, value)` returns a `Decimal` in `[0,1]` using the midpoint rank for ties. `quantile(values, q)` validates `0 <= q <= 1`, sorts `Decimal` values, and uses deterministic linear interpolation between adjacent observations.

- [ ] **Step 4: Implement broad feature calculation**

Create:

```python
@dataclass(frozen=True, slots=True)
class BroadFeatureValues:
    source_received_at_ms: int
    day_return: Decimal | None
    funding: Decimal
    open_interest: Decimal
    day_notional_volume: Decimal
    oi_change_fraction: Decimal | None
    funding_change: Decimal | None
    mark_oracle_dislocation_bps: Decimal | None
```

Function:

```python
def calculate_broad_features(
    current: PerpMarketSnapshot,
    previous: PerpMarketSnapshot | None,
    *,
    as_of_ms: int,
) -> BroadFeatureValues:
    ...
```

Validate same market for `previous`; reject future receipt times; preserve missing price state as `None` instead of inventing values.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/test_feature_math.py tests/test_broad_features.py -q
python -m ruff check src/cocomelon/features tests/test_feature_math.py tests/test_broad_features.py
python -m mypy src/cocomelon/features
```

Commit:

```bash
git add src/cocomelon/features tests/test_feature_math.py tests/test_broad_features.py
git commit -m "feat: calculate deterministic broad market features"
```

---

### Task 3: Lookahead-safe candle and microstructure feature calculators

**Files:**
- Create: `src/cocomelon/features/candles.py`
- Create: `src/cocomelon/features/microstructure.py`
- Create: `tests/test_candle_features.py`
- Create: `tests/test_microstructure_features.py`

**Interfaces:**
- Consumes: sequences of normalized `Candle`, normalized Phase 3 L2 `StreamEvent`, and `as_of_ms`.
- Produces: `CandleFeatureValues` and `MicrostructureFeatureValues`.

- [ ] **Step 1: Write candle RED tests**

Use synthetic unit-test candles only to verify arithmetic; do not label them historical market evidence. Prove:

- candles whose `end_ms > as_of_ms` are ignored;
- any candle with `received_at_ms > as_of_ms` fails closed;
- closed candles must be strictly increasing and match requested market;
- 5m return uses the latest two closed 5m closes;
- 15m return uses the latest two closed 15m closes;
- 1h return uses closes four 15m bars apart;
- 4h return uses closes sixteen 15m bars apart;
- `relative_volume_15m = last_volume / median(previous_20_volumes)` when 21 closed 15m bars are available;
- `range_expansion_15m = last_normalized_range / median(previous_20_normalized_ranges)` with normalized range `(high-low)/open`;
- realized volatility is the population standard deviation of simple close-to-close 15m returns over the latest 20 returns and remains `Decimal`.

- [ ] **Step 2: Write L2 RED tests**

From a real-shape normalized L2 `StreamEvent`, prove:

- best bid is maximum bid price and best ask is minimum ask price, independent of input ordering;
- crossed/empty books raise `ValueError`;
- spread bps uses book mid;
- visible bid/ask notional within 25 bps of mid is `sum(px * sz)`;
- imbalance is `(bid_depth - ask_depth) / (bid_depth + ask_depth)` when total depth is positive;
- exchange-time age is non-negative and future exchange timestamps fail closed;
- non-L2 events are rejected.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_candle_features.py tests/test_microstructure_features.py -q
```

Expected: FAIL because calculators do not exist.

- [ ] **Step 4: Implement candle calculator**

Expose:

```python
def calculate_candle_features(
    market: MarketId,
    *,
    candles_5m: Sequence[Candle] = (),
    candles_15m: Sequence[Candle] = (),
    as_of_ms: int,
) -> CandleFeatureValues:
    ...
```

Do not require separate 1h/4h API calls; derive 1h and 4h close-to-close returns from aligned closed 15m bars to keep live enrichment within the free REST budget.

- [ ] **Step 5: Implement microstructure calculator**

Expose:

```python
def calculate_microstructure_features(
    event: StreamEvent,
    *,
    as_of_ms: int,
    depth_band_bps: Decimal = Decimal("25"),
) -> MicrostructureFeatureValues:
    ...
```

- [ ] **Step 6: Run GREEN and commit**

```bash
python -m pytest tests/test_candle_features.py tests/test_microstructure_features.py -q
python -m ruff check src/cocomelon/features tests/test_candle_features.py tests/test_microstructure_features.py
python -m mypy src/cocomelon/features
```

Commit:

```bash
git add src/cocomelon/features/candles.py src/cocomelon/features/microstructure.py tests/test_candle_features.py tests/test_microstructure_features.py
git commit -m "feat: calculate candle and book quality features"
```

---

### Task 4: Feature assembly and baseline market regime

**Files:**
- Create: `src/cocomelon/features/assemble.py`
- Create: `src/cocomelon/features/regime.py`
- Create: `tests/test_feature_assembly.py`
- Create: `tests/test_regime.py`

**Interfaces:**
- Consumes: `BroadFeatureValues`, optional `CandleFeatureValues`, optional `MicrostructureFeatureValues`, current market identity, and provenance.
- Produces: versioned `FeatureSnapshot` plus cross-sectionally assigned volatility regime.

- [ ] **Step 1: Write RED tests**

Trend regime rules are intentionally simple and explainable:

```text
UP      = return_15m > 0 AND return_1h > 0 AND return_4h > 0
DOWN    = return_15m < 0 AND return_1h < 0 AND return_4h < 0
MIXED   = all three exist but signs do not align
UNKNOWN = any required return is missing
```

Volatility regime is cross-sectional, not an invented absolute annualized threshold:

```text
LOW     = realized_vol_15m <= 20th percentile of non-missing current values
HIGH    = realized_vol_15m >= 80th percentile
NORMAL  = between them
UNKNOWN = feature missing or fewer than 5 non-missing markets
```

Tests also prove snapshot provenance is sorted/deduplicated and the same inputs produce the same `snapshot_id` regardless mapping iteration order.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_feature_assembly.py tests/test_regime.py -q
```

- [ ] **Step 3: Implement assembly and regime functions**

Expose:

```python
def assemble_feature_snapshot(...) -> FeatureSnapshot: ...
def assign_volatility_regimes(
    snapshots: Sequence[FeatureSnapshot],
    *,
    low_quantile: Decimal = Decimal("0.20"),
    high_quantile: Decimal = Decimal("0.80"),
) -> tuple[FeatureSnapshot, ...]: ...
```

Never mutate snapshots; use `dataclasses.replace` when adding volatility regime.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_feature_assembly.py tests/test_regime.py -q
python -m ruff check src/cocomelon/features tests/test_feature_assembly.py tests/test_regime.py
python -m mypy src/cocomelon/features
```

Commit:

```bash
git add src/cocomelon/features/assemble.py src/cocomelon/features/regime.py tests/test_feature_assembly.py tests/test_regime.py
git commit -m "feat: assemble versioned feature snapshots and regimes"
```

---

### Task 5: Two-stage eligibility gate with observed-distribution thresholds

**Files:**
- Create: `src/cocomelon/scanner/__init__.py`
- Create: `src/cocomelon/scanner/eligibility.py`
- Create: `tests/test_eligibility.py`

**Interfaces:**
- Consumes: current `PerpMarketSnapshot`, its `FeatureSnapshot`, and cross-sectional peer features.
- Produces: `EligibilityThresholds` and `EligibilityDecision(rankable, deep_ready, reasons)`.

- [ ] **Step 1: Write RED tests for coarse eligibility**

Default `EligibilityConfig`:

```python
max_context_age_ms = 60_000
volume_quantile = Decimal("0.10")
oi_quantile = Decimal("0.10")
absolute_min_day_notional_volume = Decimal("0")
absolute_min_open_interest = Decimal("0")
```

Coarse ranking eligibility fails closed for:

- delisted market;
- missing/non-positive mark, mid, oracle, or previous-day price;
- future or stale context receipt time;
- non-positive max leverage;
- day volume below `max(absolute floor, current-universe 10th percentile)`;
- OI below `max(absolute floor, current-universe 10th percentile)`.

Reason strings are stable machine-readable codes such as `delisted`, `invalid_price_state`, `stale_context`, `unsupported_leverage`, `below_volume_floor`, and `below_oi_floor`.

- [ ] **Step 2: Write RED tests for deep readiness**

Deep defaults:

```python
max_book_age_ms = 5_000
hard_max_spread_bps = Decimal("50")
spread_quantile = Decimal("0.90")
depth_quantile = Decimal("0.10")
absolute_min_side_depth = Decimal("0")
```

Deep-ready requires coarse rankability plus L2 features. Observed thresholds are:

```text
spread ceiling = min(hard_max_spread_bps, 90th percentile of available peer spreads)
minimum side depth = max(absolute_min_side_depth, 10th percentile of peer min(bid_depth, ask_depth))
```

Missing L2 yields `rankable=True, deep_ready=False, reason=missing_deep_data`; it does not remove a market from ranking because the shortlist subscription is how L2 becomes available. Stale books, excessive spread, or insufficient depth keep `deep_ready=False`.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_eligibility.py -q
```

- [ ] **Step 4: Implement thresholds and gate**

Expose:

```python
def derive_eligibility_thresholds(
    snapshots: Sequence[FeatureSnapshot],
    config: EligibilityConfig,
) -> EligibilityThresholds: ...


def evaluate_eligibility(
    market_snapshot: PerpMarketSnapshot,
    features: FeatureSnapshot,
    thresholds: EligibilityThresholds,
    config: EligibilityConfig,
) -> EligibilityDecision: ...
```

Threshold derivation ignores missing microstructure values rather than fabricating them. If there are fewer than 5 deep peers, apply only hard spread/age constraints and the configured absolute depth floor.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/test_eligibility.py -q
python -m ruff check src/cocomelon/scanner tests/test_eligibility.py
python -m mypy src/cocomelon/scanner
```

Commit:

```bash
git add src/cocomelon/scanner tests/test_eligibility.py
git commit -m "feat: gate market ranking and deep readiness"
```

---

### Task 6: Direction-neutral opportunity ranker

**Files:**
- Create: `src/cocomelon/scanner/ranker.py`
- Create: `tests/test_ranker.py`

**Interfaces:**
- Consumes: feature snapshots plus eligibility decisions.
- Produces: deterministic `OpportunityRank` tuples for rankable markets only.

- [ ] **Step 1: Write RED tests for ranking invariants**

Prove:

- ineligible markets never receive a rank;
- score is in `[0,1]` and is never labeled a probability;
- ranking is invariant to input order;
- score ties are broken by canonical market name;
- missing optional features cause available component weights to renormalize, not become zero-value penalties;
- the ranker has no direction field and cannot emit LONG/SHORT;
- top reason codes correspond to the largest component contributions.

- [ ] **Step 2: Define explicit baseline weights**

Coarse weights before candle enrichment:

```python
COARSE_WEIGHTS = {
    "abs_day_return": Decimal("0.30"),
    "day_notional_volume": Decimal("0.25"),
    "open_interest": Decimal("0.20"),
    "abs_oi_change": Decimal("0.15"),
    "abs_funding": Decimal("0.10"),
}
```

Enriched weights use coarse score as one component:

```python
ENRICHED_WEIGHTS = {
    "coarse_score": Decimal("0.25"),
    "abs_return_15m": Decimal("0.15"),
    "abs_return_1h": Decimal("0.10"),
    "relative_volume_15m": Decimal("0.15"),
    "realized_vol_15m": Decimal("0.10"),
    "range_deviation": Decimal("0.10"),
    "abs_oi_change": Decimal("0.10"),
    "book_quality": Decimal("0.05"),
}
```

`range_deviation = abs(range_expansion_15m - 1)`. `book_quality` is the average of inverse-spread percentile and minimum-side-depth percentile when both exist; if missing, its weight is removed and the remaining weights renormalize.

These weights are an explainable baseline for attention allocation, not a profitability claim. Phase 9 will evaluate whether they have predictive value.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_ranker.py -q
```

- [ ] **Step 4: Implement percentile-based ranker**

Expose:

```python
def rank_opportunities(
    snapshots: Sequence[FeatureSnapshot],
    decisions: Sequence[EligibilityDecision],
    *,
    mode: Literal["coarse", "enriched"],
) -> tuple[OpportunityRank, ...]:
    ...
```

Every raw component is converted to a current-universe percentile before weighting so dollar volume and fractional returns are comparable without arbitrary unit scaling.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/test_ranker.py -q
python -m ruff check src/cocomelon/scanner/ranker.py tests/test_ranker.py
python -m mypy src/cocomelon/scanner/ranker.py
```

Commit:

```bash
git add src/cocomelon/scanner/ranker.py tests/test_ranker.py
git commit -m "feat: rank direction-neutral market opportunities"
```

---

### Task 7: Dynamic shortlist with hysteresis and Phase 3 watchlist integration

**Files:**
- Create: `src/cocomelon/scanner/shortlist.py`
- Create: `tests/test_shortlist.py`
- Modify: `src/cocomelon/domain/features.py`

**Interfaces:**
- Consumes: enriched/coarse ranks, eligibility, optional pinned markets, existing `DeepWatchlistManager`.
- Produces: deterministic `ShortlistDelta` and Phase 3 `SubscriptionPlan`.

- [ ] **Step 1: Write RED shortlist tests**

Default configuration:

```python
target_size = 20
retention_rank = 30
ranked_watchlist_size = 40
```

Prove:

- no more than `target_size` non-pinned markets are selected;
- pinned markets are retained even if they would exceed target size, leaving the Phase 3 subscription safety ceiling as final resource protection;
- newly ineligible markets are removed immediately;
- an existing eligible shortlist market ranked 21-30 is retained before a new lower-priority entrant, reducing subscription churn;
- current markets worse than `retention_rank` are removable;
- stable ties use canonical market name;
- `added`, `removed`, and `current` are deterministic tuples;
- top `ranked_watchlist_size` markets are exposed as Tier B enrichment candidates independently from the Tier C target shortlist.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_shortlist.py -q
```

- [ ] **Step 3: Implement shortlist manager**

Expose:

```python
@dataclass(frozen=True, slots=True)
class ShortlistConfig:
    target_size: int = 20
    retention_rank: int = 30
    ranked_watchlist_size: int = 40


class DynamicShortlistManager:
    def reconcile(
        self,
        ranks: Sequence[OpportunityRank],
        decisions: Sequence[EligibilityDecision],
        *,
        pinned_markets: Iterable[MarketId] = (),
    ) -> ShortlistDelta:
        ...
```

Also expose:

```python
def build_subscription_plan(
    deep_watchlist: DeepWatchlistManager,
    shortlist: ShortlistDelta,
    *,
    pinned_markets: Iterable[MarketId] = (),
) -> SubscriptionPlan:
    return deep_watchlist.reconcile(shortlist.current, pinned_markets=pinned_markets)
```

This function computes subscriptions only; it does not send network messages.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_shortlist.py -q
python -m ruff check src/cocomelon/scanner/shortlist.py tests/test_shortlist.py
python -m mypy src/cocomelon/scanner/shortlist.py
```

Commit:

```bash
git add src/cocomelon/scanner/shortlist.py src/cocomelon/domain/features.py tests/test_shortlist.py
git commit -m "feat: manage ranked dynamic market shortlist"
```

---

### Task 8: Broad-to-deep scanner orchestration

**Files:**
- Create: `src/cocomelon/scanner/engine.py`
- Create: `tests/test_scanner_engine.py`

**Interfaces:**
- Consumes: current/previous `PerpMarketSnapshot` mappings, optional 5m/15m candle mappings, optional latest L2 event mappings, `as_of_ms`, `DynamicShortlistManager`, and `DeepWatchlistManager`.
- Produces: a complete immutable `ScanResult` without trading decisions.

- [ ] **Step 1: Write RED end-to-end deterministic scanner tests**

Build a synthetic unit-test universe of at least 30 markets and prove:

1. every current market receives a broad feature snapshot unless its input is invalid/lookahead;
2. delisted/stale/invalid-price markets cannot rank;
3. coarse ranking spans the dynamically provided universe;
4. Tier B enrichment candidates come from coarse ranks and are bounded by `ranked_watchlist_size`;
5. candle features enrich only markets for which candle inputs are supplied;
6. missing L2 keeps a candidate rankable but not deep-ready;
7. fresh narrow-spread adequate-depth L2 can make it deep-ready on the next scan;
8. shortlist transitions are deterministic and hysteretic;
9. resulting Phase 3 subscription plan contains only public broad/deep feeds and respects the watchlist manager's ceiling;
10. output contains no strategy direction, risk sizing, or order plan.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_scanner_engine.py -q
```

- [ ] **Step 3: Implement scanner engine**

Expose:

```python
class FeatureScanner:
    def scan(
        self,
        current_markets: Mapping[str, PerpMarketSnapshot],
        *,
        previous_markets: Mapping[str, PerpMarketSnapshot] = MappingProxyType({}),
        candles_5m: Mapping[str, Sequence[Candle]] = MappingProxyType({}),
        candles_15m: Mapping[str, Sequence[Candle]] = MappingProxyType({}),
        l2_books: Mapping[str, StreamEvent] = MappingProxyType({}),
        as_of_ms: int,
        pinned_markets: Iterable[MarketId] = (),
    ) -> ScanResult:
        ...
```

Do not actually use mutable mappings as default arguments in production; implement with `None` defaults and normalize internally even though the conceptual signature above shows empty mappings.

Pipeline order:

```text
broad features for all
-> broad threshold derivation
-> coarse eligibility
-> coarse percentile rank
-> Tier B candidate list
-> optional candle/L2 enrichment for candidates
-> regime assignment
-> re-derived deep thresholds
-> eligibility/deep-readiness refresh
-> enriched rank where features exist, coarse rank fallback otherwise
-> hysteretic Tier C shortlist
-> Phase 3 subscription plan
-> immutable ScanResult
```

A candidate missing enrichment remains rankable with its coarse rank rather than being assigned fabricated zeros.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_scanner_engine.py -q
python -m ruff check src/cocomelon/scanner src/cocomelon/features tests/test_scanner_engine.py
python -m mypy src/cocomelon/scanner src/cocomelon/features
```

Commit:

```bash
git add src/cocomelon/scanner/engine.py tests/test_scanner_engine.py
git commit -m "feat: orchestrate broad-to-deep market scanning"
```

---

### Task 9: Read-only operator scan and mainnet wiring smoke

**Files:**
- Modify: `src/cocomelon/cli.py`
- Create: `tests/test_scan_cli.py`

**Interfaces:**
- `cocomelon scan-once --limit 20` refreshes the real mainnet market registry, runs **broad-only** Phase 4 eligibility/ranking across the entire discovered universe, and prints a bounded summary. It never fetches user data or sends orders.

- [ ] **Step 1: Write CLI RED tests with injected registry/scanner**

Prove:

- default output limit is 20 and hard maximum is 100;
- command rejects wallet/key/order/live flags because argparse does not define them;
- registry refresh results for all markets are passed to broad scanning;
- JSON output contains market, ordinal, direction-neutral score, rankability reasons, and feature snapshot id;
- no `LONG`, `SHORT`, leverage, position size, or order fields exist.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_scan_cli.py -q
```

- [ ] **Step 3: Implement bounded CLI**

Reuse `Settings`, `InfoClient`, and `MarketRegistry`; do not add a second HTTP stack. The command uses one registry refresh and broad features only, so it does not multiply candle requests across hundreds of markets. Full candle/L2 enrichment remains driven by stored/streamed Tier B/C data through `FeatureScanner`.

- [ ] **Step 4: Run deterministic GREEN**

```bash
python -m pytest tests/test_scan_cli.py -q
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

- [ ] **Step 5: Optional temporary public-mainnet smoke**

Only after deterministic CI is green, use a temporary branch-scoped GitHub Actions job if connector execution cannot run the command directly. Run exactly:

```bash
cocomelon scan-once --limit 20
```

Capture only public output counts/top markets; no user/account endpoints and no `post` action. Remove the temporary workflow before merge. A network smoke is verification, not a permanent CI dependency.

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/cli.py tests/test_scan_cli.py
git commit -m "feat: add read-only market scanner command"
```

---

### Task 10: Phase 4 verification, continuity docs, and merge gate

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`

**Interfaces:**
- Records exact Phase 4 branch head, CI, any read-only smoke evidence, test evidence, and Phase 5 next action.

- [ ] **Step 1: Full deterministic verification**

Run through Python 3.12 CI:

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

- [ ] **Step 2: Requirement audit**

Verify line by line:

- scanner covers every dynamically supplied discovered market;
- delisted/stale/invalid markets cannot rank;
- coarse eligibility and opportunity ranking remain separate;
- feature windows are lookahead-safe;
- multi-timeframe return/trend, realized-volatility, range, relative-volume, funding/OI, spread/depth, and baseline regime features are implemented;
- missing Tier B/C inputs never become fabricated values;
- ranking is direction-neutral and deterministic;
- shortlist is bounded, deterministic, explainable, and hysteretic;
- Phase 3 subscription ceiling remains final protection;
- feature snapshots are versioned/provenanced and deterministically identified;
- no strategy/risk/order/live functionality was introduced.

- [ ] **Step 3: Update continuity docs**

Record exact evidence and set the next phase to **Phase 5 — baseline strategy engines** only after Phase 4 passes.

- [ ] **Step 4: Open/finish Phase 4 PR**

Use an expected-head SHA when merging. Verify `main` points to the merge commit and deterministic CI remains green.

---

## Self-review

- **Spec coverage:** liquidity/spread/depth, multi-timeframe returns/trend, realized volatility/range, relative volume, funding/OI, regime, eligibility, opportunity ranking, dynamic shortlist, and feature snapshot versioning each map to explicit tasks.
- **Tiering consistency:** L2 is not required across the whole universe. Coarse rankability precedes deep subscription; deep readiness is evaluated once L2 exists. This resolves the Tier A/Tier C circularity without weakening the future strategy gate.
- **Safety coverage:** no user/account data, signing, orders, risk sizing, strategy direction, ML, or live execution exists in Phase 4 interfaces.
- **Lookahead coverage:** future-received inputs fail closed; future/open candles are excluded from closed-window calculations; feature snapshots carry `as_of_ms` and provenance.
- **Data-integrity coverage:** no missing feature is replaced with invented zero; percentile score weights renormalize across genuinely available components.
- **Rate-limit coverage:** the permanent live CLI is broad-only; no plan step creates hundreds of per-market candle calls. Candle enrichment is bounded and consumes Tier B data already fetched/recorded by the system.
- **Placeholder scan:** no TODO/TBD implementation requirements remain in this plan.
- **Type consistency:** all downstream tasks consume the domain contracts defined in Task 1; `MarketId`, `PerpMarketSnapshot`, `Candle`, `StreamEvent`, `DeepWatchlistManager`, and `SubscriptionPlan` reuse existing names exactly.
