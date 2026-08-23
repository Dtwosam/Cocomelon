import importlib
from dataclasses import fields
from decimal import Decimal

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId

ranker_module = importlib.import_module("cocomelon.scanner.ranker")
rank_opportunities = ranker_module.rank_opportunities


def _snapshot(
    coin: str,
    *,
    day_return: Decimal | None = Decimal("0.01"),
    volume: Decimal = Decimal("1000000"),
    open_interest: Decimal = Decimal("1000"),
    oi_change: Decimal | None = Decimal("0.01"),
    funding: Decimal = Decimal("0.0001"),
    return_15m: Decimal | None = Decimal("0.01"),
    return_1h: Decimal | None = Decimal("0.02"),
    relative_volume: Decimal | None = Decimal("1.1"),
    realized_vol: Decimal | None = Decimal("0.01"),
    range_expansion: Decimal | None = Decimal("1.1"),
    spread_bps: Decimal | None = Decimal("5"),
    bid_depth: Decimal | None = Decimal("1000"),
    ask_depth: Decimal | None = Decimal("900"),
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", coin),
        as_of_ms=1_000,
        source_received_at_ms=900,
        schema_version=1,
        day_return=day_return,
        funding=funding,
        open_interest=open_interest,
        day_notional_volume=volume,
        oi_change_fraction=oi_change,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("1"),
        return_5m=Decimal("0.005"),
        return_15m=return_15m,
        return_1h=return_1h,
        return_4h=Decimal("0.03"),
        realized_vol_15m=realized_vol,
        range_expansion_15m=range_expansion,
        relative_volume_15m=relative_volume,
        spread_bps=spread_bps,
        bid_depth_25bps=bid_depth,
        ask_depth_25bps=ask_depth,
        book_imbalance=None,
        book_age_ms=None if spread_bps is None else 100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("hyperliquid-mainnet-info",),
    )


def _decision(coin: str, *, rankable: bool = True) -> EligibilityDecision:
    return EligibilityDecision(
        market=MarketId("", coin),
        rankable=rankable,
        deep_ready=False,
        reasons=() if rankable else ("delisted",),
    )


def _signature(ranks: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            rank.market.canonical,
            rank.ordinal,
            rank.score,
            tuple(
                (item.name, item.raw_value, item.percentile, item.weight, item.contribution)
                for item in rank.components
            ),
            rank.reason_codes,
        )
        for rank in ranks
    )


def test_coarse_ranker_excludes_ineligible_and_is_input_order_invariant() -> None:
    snapshots = (
        _snapshot("A", day_return=Decimal("0.01"), volume=Decimal("100")),
        _snapshot("B", day_return=Decimal("0.03"), volume=Decimal("300")),
        _snapshot("C", day_return=Decimal("0.02"), volume=Decimal("200")),
    )
    decisions = (_decision("A"), _decision("B"), _decision("C", rankable=False))

    first = rank_opportunities(snapshots, decisions, mode="coarse")
    second = rank_opportunities(
        tuple(reversed(snapshots)),
        tuple(reversed(decisions)),
        mode="coarse",
    )

    assert _signature(first) == _signature(second)
    assert tuple(rank.market.coin for rank in first) == ("B", "A")
    assert all(Decimal("0") <= rank.score <= Decimal("1") for rank in first)
    assert all(rank.market.coin != "C" for rank in first)


def test_score_ties_are_broken_by_canonical_market_name() -> None:
    snapshots = (_snapshot("Z"), _snapshot("A"))
    decisions = (_decision("Z"), _decision("A"))

    ranks = rank_opportunities(snapshots, decisions, mode="coarse")

    assert tuple(rank.market.coin for rank in ranks) == ("A", "Z")
    assert ranks[0].score == ranks[1].score


def test_missing_optional_features_renormalize_available_weights() -> None:
    complete = _snapshot("COMPLETE", day_return=Decimal("0.02"), oi_change=Decimal("0.02"))
    sparse = _snapshot("SPARSE", day_return=None, oi_change=None)
    peer = _snapshot("PEER", day_return=Decimal("0.01"), oi_change=Decimal("0.01"))
    decisions = (_decision("COMPLETE"), _decision("SPARSE"), _decision("PEER"))

    ranks = rank_opportunities((complete, sparse, peer), decisions, mode="coarse")
    sparse_rank = next(rank for rank in ranks if rank.market.coin == "SPARSE")

    assert tuple(item.name for item in sparse_rank.components) == (
        "day_notional_volume",
        "open_interest",
        "abs_funding",
    )
    assert sum((item.weight for item in sparse_rank.components), Decimal("0")) == Decimal("1")
    assert all(item.raw_value != Decimal("0") for item in sparse_rank.components)


def test_enriched_ranker_uses_available_features_and_optional_book_quality() -> None:
    snapshots = (
        _snapshot(
            "A",
            return_15m=Decimal("0.03"),
            return_1h=Decimal("0.04"),
            relative_volume=Decimal("2"),
            realized_vol=Decimal("0.03"),
            range_expansion=Decimal("1.8"),
            spread_bps=Decimal("2"),
            bid_depth=Decimal("3000"),
            ask_depth=Decimal("2500"),
        ),
        _snapshot(
            "B",
            return_15m=Decimal("0.01"),
            return_1h=Decimal("0.01"),
            relative_volume=Decimal("1"),
            realized_vol=Decimal("0.01"),
            range_expansion=Decimal("1.1"),
            spread_bps=Decimal("10"),
            bid_depth=Decimal("1000"),
            ask_depth=Decimal("900"),
        ),
        _snapshot(
            "NOBOOK",
            return_15m=Decimal("0.02"),
            return_1h=Decimal("0.02"),
            relative_volume=Decimal("1.5"),
            realized_vol=Decimal("0.02"),
            range_expansion=Decimal("1.4"),
            spread_bps=None,
            bid_depth=None,
            ask_depth=None,
        ),
    )
    decisions = tuple(_decision(item.market.coin) for item in snapshots)

    ranks = rank_opportunities(snapshots, decisions, mode="enriched")
    no_book = next(rank for rank in ranks if rank.market.coin == "NOBOOK")
    a_rank = next(rank for rank in ranks if rank.market.coin == "A")

    assert "book_quality" not in tuple(item.name for item in no_book.components)
    assert sum((item.weight for item in no_book.components), Decimal("0")) == Decimal("1")
    assert "book_quality" in tuple(item.name for item in a_rank.components)
    assert ranks[0].market.coin == "A"


def test_reason_codes_follow_component_contribution_order() -> None:
    snapshots = (
        _snapshot(
            "A",
            day_return=Decimal("0.10"),
            volume=Decimal("1000"),
            open_interest=Decimal("100"),
            oi_change=Decimal("0.01"),
            funding=Decimal("0.0001"),
        ),
        _snapshot(
            "B",
            day_return=Decimal("0.01"),
            volume=Decimal("100"),
            open_interest=Decimal("1000"),
            oi_change=Decimal("0.10"),
            funding=Decimal("0.01"),
        ),
    )
    decisions = (_decision("A"), _decision("B"))

    ranks = rank_opportunities(snapshots, decisions, mode="coarse")
    rank = next(item for item in ranks if item.market.coin == "A")
    expected = tuple(
        component.name
        for component in sorted(
            rank.components,
            key=lambda component: (-component.contribution, component.name),
        )
    )

    assert rank.reason_codes == expected


def test_rank_contract_has_no_direction_or_probability_field() -> None:
    ranks = rank_opportunities((_snapshot("A"),), (_decision("A"),), mode="coarse")
    rank = ranks[0]
    field_names = {field.name for field in fields(rank)}

    assert "direction" not in field_names
    assert "probability" not in field_names
    assert "long" not in str(rank).lower()
    assert "short" not in str(rank).lower()
