from decimal import Decimal

import pytest
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    OpportunityRank,
    ScoreComponent,
    ShortlistDelta,
    TrendRegime,
    VolatilityRegime,
)

from cocomelon.domain.market import MarketId


def _feature_snapshot(**overrides: object) -> FeatureSnapshot:
    values: dict[str, object] = {
        "market": MarketId("", "BTC"),
        "as_of_ms": 1_000,
        "source_received_at_ms": 900,
        "schema_version": 1,
        "day_return": Decimal("0.01"),
        "funding": Decimal("0.0001"),
        "open_interest": Decimal("100"),
        "day_notional_volume": Decimal("1000000"),
        "oi_change_fraction": None,
        "funding_change": None,
        "mark_oracle_dislocation_bps": Decimal("2"),
        "return_5m": None,
        "return_15m": None,
        "return_1h": None,
        "return_4h": None,
        "realized_vol_15m": None,
        "range_expansion_15m": None,
        "relative_volume_15m": None,
        "spread_bps": None,
        "bid_depth_25bps": None,
        "ask_depth_25bps": None,
        "book_imbalance": None,
        "book_age_ms": None,
        "trend_regime": TrendRegime.UNKNOWN,
        "volatility_regime": VolatilityRegime.UNKNOWN,
        "provenance": ("hyperliquid-mainnet-info",),
    }
    values.update(overrides)
    return FeatureSnapshot(**values)  # type: ignore[arg-type]


def test_feature_snapshot_identity_is_deterministic_and_provenance_is_canonical() -> None:
    first = _feature_snapshot(
        provenance=("z-source", "hyperliquid-mainnet-info", "z-source"),
    )
    second = _feature_snapshot(
        provenance=("hyperliquid-mainnet-info", "z-source"),
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.provenance == ("hyperliquid-mainnet-info", "z-source")
    assert len(first.snapshot_id) == 24


def test_feature_snapshot_rejects_future_source_receipt() -> None:
    with pytest.raises(ValueError, match="source_received_at_ms"):
        _feature_snapshot(source_received_at_ms=1_001)


def test_feature_snapshot_rejects_negative_book_age() -> None:
    with pytest.raises(ValueError, match="book_age_ms"):
        _feature_snapshot(book_age_ms=-1)


def test_feature_snapshot_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        _feature_snapshot(schema_version=0)


def test_score_component_enforces_percentile_weight_and_contribution_bounds() -> None:
    component = ScoreComponent(
        name="abs_day_return",
        raw_value=Decimal("0.03"),
        percentile=Decimal("0.75"),
        weight=Decimal("0.30"),
        contribution=Decimal("0.225"),
    )
    assert component.contribution == Decimal("0.225")

    with pytest.raises(ValueError, match="percentile"):
        ScoreComponent(
            name="bad",
            raw_value=Decimal("1"),
            percentile=Decimal("1.01"),
            weight=Decimal("0.5"),
            contribution=Decimal("0.5"),
        )


def test_opportunity_rank_requires_positive_ordinal_and_unit_score() -> None:
    component = ScoreComponent(
        name="abs_day_return",
        raw_value=Decimal("0.03"),
        percentile=Decimal("0.75"),
        weight=Decimal("1"),
        contribution=Decimal("0.75"),
    )
    rank = OpportunityRank(
        market=MarketId("", "BTC"),
        ordinal=1,
        score=Decimal("0.75"),
        components=(component,),
        reason_codes=("abs_day_return",),
    )
    assert rank.ordinal == 1

    with pytest.raises(ValueError, match="ordinal"):
        OpportunityRank(
            market=MarketId("", "BTC"),
            ordinal=0,
            score=Decimal("0.75"),
            components=(component,),
            reason_codes=(),
        )


def test_eligibility_and_shortlist_contracts_are_immutable_tuples() -> None:
    btc = MarketId("", "BTC")
    eth = MarketId("", "ETH")
    decision = EligibilityDecision(
        market=btc,
        rankable=True,
        deep_ready=False,
        reasons=("missing_deep_data",),
    )
    delta = ShortlistDelta(added=(btc,), removed=(eth,), current=(btc,))

    assert decision.reasons == ("missing_deep_data",)
    assert delta.current == (btc,)
