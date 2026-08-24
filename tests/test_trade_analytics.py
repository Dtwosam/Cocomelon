from decimal import Decimal

import pytest

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.journal.analytics import compute_trade_analytics


def mark(timestamp_ms: int, price: str, key: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=timestamp_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="SOL",
        exchange_time_ms=None,
        event_key=key,
        payload_json=f'{{"mark_px":"{price}"}}',
        event_kind="active_asset_ctx",
    )


def test_long_net_pnl_r_slippage_and_excursions_use_real_marks() -> None:
    result = compute_trade_analytics(
        direction=Direction.LONG,
        entry_price=Decimal("100"),
        entry_reference_price=Decimal("99.9"),
        exit_price=Decimal("102"),
        exit_reference_price=Decimal("102.2"),
        opened_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("20"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.459"),
        funding_cash_pnl=Decimal("-0.1"),
        initial_risk_amount=Decimal("25"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        mark_observations=(
            mark(900, "200", "future-outside-before"),
            mark(1_100, "98", "ctx-low"),
            mark(1_500, "103", "ctx-high"),
            mark(2_100, "1", "outside-after"),
        ),
        known_gap_intervals=(),
    )

    assert result.net_pnl == Decimal("18.991")
    assert result.net_r == Decimal("0.75964")
    assert result.entry_slippage_fraction == Decimal("0.001001001001001001001001001001")
    assert result.exit_slippage_fraction == Decimal("0.001956947162426614481409001957")
    assert result.mfe is not None and result.mfe.price == Decimal("103")
    assert result.mfe.source_event_key == "ctx-high"
    assert result.mae is not None and result.mae.price == Decimal("98")
    assert result.mae.source_event_key == "ctx-low"
    assert result.mfe.complete is True
    assert result.mae.complete is True


def test_short_slippage_and_excursion_signs_reverse_correctly() -> None:
    result = compute_trade_analytics(
        direction=Direction.SHORT,
        entry_price=Decimal("100"),
        entry_reference_price=Decimal("100.1"),
        exit_price=Decimal("95"),
        exit_reference_price=Decimal("94.9"),
        opened_quantity=Decimal("4"),
        gross_realized_pnl=Decimal("20"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("1"),
        initial_risk_amount=Decimal("10"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        mark_observations=(mark(1_200, "104", "ctx-bad"), mark(1_800, "93", "ctx-good")),
        known_gap_intervals=(),
    )

    assert result.net_pnl == Decimal("21")
    assert result.net_r == Decimal("2.1")
    assert result.entry_slippage_fraction > Decimal("0")
    assert result.exit_slippage_fraction > Decimal("0")
    assert result.mfe is not None and result.mfe.price == Decimal("93")
    assert result.mae is not None and result.mae.price == Decimal("104")


def test_favorable_slippage_remains_signed_and_has_currency_amounts() -> None:
    result = compute_trade_analytics(
        direction=Direction.LONG,
        entry_price=Decimal("99"),
        entry_reference_price=Decimal("100"),
        exit_price=Decimal("105"),
        exit_reference_price=Decimal("104"),
        opened_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("60"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        initial_risk_amount=Decimal("25"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        mark_observations=(mark(1_500, "105", "ctx-favorable"),),
        known_gap_intervals=(),
    )

    assert result.entry_slippage_amount == Decimal("-10")
    assert result.exit_slippage_amount == Decimal("-10")
    assert result.entry_slippage_fraction == Decimal("-0.01")
    assert result.exit_slippage_fraction == Decimal("-0.009615384615384615384615384615")


def test_partial_exit_slippage_uses_each_plan_reference_price() -> None:
    result = compute_trade_analytics(
        direction=Direction.LONG,
        entry_price=Decimal("100"),
        entry_reference_price=Decimal("100"),
        exit_price=Decimal("102.8"),
        exit_reference_price=Decimal("103"),
        opened_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("28"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        initial_risk_amount=Decimal("25"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        mark_observations=(mark(1_500, "103", "ctx-middle"),),
        known_gap_intervals=(),
        exit_slippage_legs=(
            (Decimal("102"), Decimal("103"), Decimal("6")),
            (Decimal("104"), Decimal("103"), Decimal("4")),
        ),
    )

    assert result.exit_slippage_amount == Decimal("2")
    assert result.exit_slippage_fraction == Decimal("0.001941747572815533980582524272")


def test_partial_reduction_uses_quantity_open_at_excursion_extreme() -> None:
    result = compute_trade_analytics(
        direction=Direction.LONG,
        entry_price=Decimal("100"),
        entry_reference_price=Decimal("100"),
        exit_price=Decimal("104"),
        exit_reference_price=Decimal("104"),
        opened_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("40"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        initial_risk_amount=Decimal("25"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        mark_observations=(
            mark(1_200, "99", "ctx-low"),
            mark(1_600, "110", "ctx-high-after-reduction"),
        ),
        known_gap_intervals=(),
        quantity_reductions=((1_500, Decimal("6")),),
    )

    assert result.mfe.price == Decimal("110")
    assert result.mfe.currency == Decimal("40")
    assert result.mfe.r_multiple == Decimal("1.6")
    assert result.mae.currency == Decimal("10")


def test_gap_intersection_marks_mfe_and_mae_incomplete() -> None:
    result = compute_trade_analytics(
        direction=Direction.LONG,
        entry_price=Decimal("100"),
        entry_reference_price=Decimal("100"),
        exit_price=Decimal("101"),
        exit_reference_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("1"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        initial_risk_amount=Decimal("5"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        mark_observations=(mark(1_200, "99", "ctx-low"), mark(1_800, "102", "ctx-high")),
        known_gap_intervals=((1_400, 1_600),),
    )

    assert result.mfe is not None and result.mfe.complete is False
    assert result.mae is not None and result.mae.complete is False


def test_missing_initial_risk_and_no_marks_fail_research_readiness() -> None:
    kwargs = dict(
        direction=Direction.LONG,
        entry_price=Decimal("100"),
        entry_reference_price=Decimal("100"),
        exit_price=Decimal("101"),
        exit_reference_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("1"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        mark_observations=(),
        known_gap_intervals=(),
    )
    with pytest.raises(ValueError, match="initial_risk_amount"):
        compute_trade_analytics(initial_risk_amount=Decimal("0"), **kwargs)

    with pytest.raises(ValueError, match="mark observation"):
        compute_trade_analytics(initial_risk_amount=Decimal("5"), **kwargs)
