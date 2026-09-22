from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import (
    DecisionAction,
    ExecutionCostAssumptions,
)
from cocomelon.research.historical_context_occupancy import (
    evaluate_context_occupancy,
)
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)
from cocomelon.research.historical_learning import DirectionalOutcome

HYPE = MarketId(dex="", coin="HYPE")
HOUR = 3_600_000
FOUR_HOURS = 14_400_000
CONTEXT = "down/bearish/near_basket"


def _row(
    *,
    anchor_index: int,
    long_return: str,
    context_matches: bool = True,
) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * HOUR
    feature = HistoricalFeatureRow(
        market=HYPE,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=None,
        return_15m=None,
        return_1h=Decimal("-0.01"),
        return_4h=Decimal("-0.02"),
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0"),
        funding_age_ms=0,
        candle_15m_age_ms=None,
        trend_regime=TrendRegime.UNKNOWN,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
        basket_median_return_1h=Decimal("-0.01"),
        basket_breadth_positive_1h=Decimal("0.25"),
        relative_return_zscore_1h_vs_basket=(
            Decimal("0") if context_matches else Decimal("-1.2")
        ),
        schema_version=3,
    )
    realized = Decimal(long_return)
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=HYPE,
            interval="1h",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + FOUR_HOURS,
            horizon_ms=FOUR_HOURS,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + realized),
            long_gross_return=realized,
            short_gross_return=-realized,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _zero_costs() -> ExecutionCostAssumptions:
    return ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )


def test_context_occupancy_removes_overlapping_4h_signals() -> None:
    rows = tuple(
        _row(anchor_index=index, long_return="0.02")
        for index in range(1, 17)
    )

    evaluation = evaluate_context_occupancy(
        rows,
        market=HYPE,
        context=CONTEXT,
        direction=DecisionAction.LONG,
        horizon_ms=FOUR_HOURS,
        costs=_zero_costs(),
        stability_blocks=4,
        min_block_trades=1,
    )

    assert evaluation.raw_match_count == 16
    assert evaluation.trade_count == 4
    assert evaluation.occupied_skip_count == 12
    assert evaluation.total_realized_net_return == Decimal("0.08")
    assert evaluation.mean_realized_net_return == Decimal("0.02")
    assert evaluation.positive_rate == Decimal("1")
    assert evaluation.stable is True
    assert [block.raw_match_count for block in evaluation.blocks] == [4, 4, 4, 4]
    assert [block.trade_count for block in evaluation.blocks] == [1, 1, 1, 1]
    assert [block.occupied_skip_count for block in evaluation.blocks] == [3, 3, 3, 3]


def test_context_occupancy_rejects_one_losing_chronological_block() -> None:
    executed_returns = {
        1: "0.02",
        5: "0.02",
        9: "-0.03",
        13: "0.02",
    }
    rows = tuple(
        _row(
            anchor_index=index,
            long_return=executed_returns.get(index, "0.50"),
        )
        for index in range(1, 17)
    )

    evaluation = evaluate_context_occupancy(
        rows,
        market=HYPE,
        context=CONTEXT,
        direction=DecisionAction.LONG,
        horizon_ms=FOUR_HOURS,
        costs=_zero_costs(),
        stability_blocks=4,
        min_block_trades=1,
    )

    assert evaluation.mean_realized_net_return == Decimal("0.0075")
    assert evaluation.mean_realized_net_return > 0
    assert evaluation.blocks[2].mean_realized_net_return == Decimal("-0.03")
    assert evaluation.stable is False


def test_context_occupancy_subtracts_costs_from_executed_trades() -> None:
    rows = tuple(
        _row(anchor_index=index, long_return="0.002")
        for index in range(1, 17)
    )

    evaluation = evaluate_context_occupancy(
        rows,
        market=HYPE,
        context=CONTEXT,
        direction=DecisionAction.LONG,
        horizon_ms=FOUR_HOURS,
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.003"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        stability_blocks=4,
        min_block_trades=1,
    )

    assert evaluation.mean_realized_net_return == Decimal("-0.001")
    assert evaluation.stable is False


def test_context_occupancy_counts_only_exact_context_matches() -> None:
    rows = tuple(
        _row(
            anchor_index=index,
            long_return="0.02",
            context_matches=index % 2 == 1,
        )
        for index in range(1, 17)
    )

    evaluation = evaluate_context_occupancy(
        rows,
        market=HYPE,
        context=CONTEXT,
        direction=DecisionAction.LONG,
        horizon_ms=FOUR_HOURS,
        costs=_zero_costs(),
        stability_blocks=4,
        min_block_trades=1,
    )

    assert evaluation.raw_match_count == 8
    assert evaluation.trade_count == 4
    assert evaluation.occupied_skip_count == 4


def test_context_occupancy_rejects_duplicate_target_anchor() -> None:
    rows = [
        _row(anchor_index=index, long_return="0.02")
        for index in range(1, 9)
    ]
    rows.append(rows[0])

    with pytest.raises(ValueError, match="duplicate target market/horizon anchor"):
        evaluate_context_occupancy(
            rows,
            market=HYPE,
            context=CONTEXT,
            direction=DecisionAction.LONG,
            horizon_ms=FOUR_HOURS,
            costs=_zero_costs(),
            stability_blocks=2,
            min_block_trades=1,
        )
