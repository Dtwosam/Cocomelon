from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import FundingRate, MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.funding import (
    FundingAccrual,
    FundingGap,
    funding_cash_delta,
    reconcile_funding_boundary,
)

MARKET = MarketId(dex="", coin="SOL")
BOUNDARY = 3_600_000


def position(
    *, side: PositionSide = PositionSide.LONG, opened_at_ms: int = 1_000
) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=side,
        quantity=Decimal("2"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95") if side is PositionSide.LONG else Decimal("105"),
        opening_plan_id="open-1",
        opened_at_ms=opened_at_ms,
        updated_at_ms=opened_at_ms,
    )


def oracle_ctx(
    *,
    received_ms: int = BOUNDARY - 100,
    market: MarketId = MARKET,
    oracle: str = "100",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=market,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp(received_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"ctx:{market.canonical}:{received_ms}",
        payload={
            "mark_px": Decimal("100"),
            "mid_px": Decimal("100"),
            "oracle_px": Decimal(oracle),
            "funding": Decimal("0.001"),
            "open_interest": Decimal("1000"),
        },
    )


def funding_record(
    *,
    rate: str = "0.001",
    time_ms: int = BOUNDARY,
    market: MarketId = MARKET,
    received_at_ms: int = BOUNDARY + 1_000,
) -> FundingRate:
    return FundingRate(
        market=market,
        time_ms=time_ms,
        funding_rate=Decimal(rate),
        premium=Decimal("0"),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def test_funding_cash_delta_signs_long_and_short_correctly() -> None:
    assert funding_cash_delta(
        Decimal("2"), Decimal("100"), Decimal("0.001")
    ) == Decimal("-0.200")
    assert funding_cash_delta(
        Decimal("-2"), Decimal("100"), Decimal("0.001")
    ) == Decimal("0.200")
    assert funding_cash_delta(
        Decimal("2"), Decimal("100"), Decimal("-0.001")
    ) == Decimal("0.200")
    assert funding_cash_delta(
        Decimal("-2"), Decimal("100"), Decimal("-0.001")
    ) == Decimal("-0.200")


def test_reconcile_pairs_exact_record_with_pre_boundary_oracle() -> None:
    result = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(),
        funding_record(),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(result, FundingAccrual)
    assert result.market == MARKET
    assert result.boundary_ms == BOUNDARY
    assert result.signed_quantity == Decimal("2")
    assert result.oracle_price == Decimal("100")
    assert result.funding_rate == Decimal("0.001")
    assert result.cash_delta == Decimal("-0.200")
    assert result.oracle_event_key == f"ctx:{MARKET.canonical}:{BOUNDARY - 100}"


def test_short_positive_funding_is_credit() -> None:
    result = reconcile_funding_boundary(
        position(side=PositionSide.SHORT),
        BOUNDARY,
        oracle_ctx(),
        funding_record(),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(result, FundingAccrual)
    assert result.signed_quantity == Decimal("-2")
    assert result.cash_delta == Decimal("0.200")


def test_deterministic_event_id_makes_reconciliation_idempotent_for_store_layer() -> None:
    first = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(),
        funding_record(),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )
    second = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(),
        funding_record(),
        now_ms=BOUNDARY + 50_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(first, FundingAccrual)
    assert isinstance(second, FundingAccrual)
    assert first.accrual_id == second.accrual_id


def test_funding_event_id_ignores_mutable_position_state_for_same_boundary() -> None:
    original = position()
    mutated = replace(
        original,
        updated_at_ms=BOUNDARY + 500,
        cumulative_funding=Decimal("-0.2"),
        latest_mark=Decimal("99"),
    )
    first = reconcile_funding_boundary(
        original,
        BOUNDARY,
        oracle_ctx(),
        funding_record(),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )
    second = reconcile_funding_boundary(
        mutated,
        BOUNDARY,
        oracle_ctx(),
        funding_record(),
        now_ms=BOUNDARY + 50_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(first, FundingAccrual)
    assert isinstance(second, FundingAccrual)
    assert first.position_id != second.position_id
    assert first.accrual_id == second.accrual_id


def test_position_must_be_open_before_boundary() -> None:
    result = reconcile_funding_boundary(
        position(opened_at_ms=BOUNDARY),
        BOUNDARY,
        oracle_ctx(),
        funding_record(),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(result, FundingGap)
    assert result.reason == "POSITION_NOT_OPEN_ACROSS_BOUNDARY"


def test_funding_market_and_time_must_match_exactly() -> None:
    wrong_market = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(),
        funding_record(market=MarketId(dex="", coin="BTC")),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )
    wrong_time = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(),
        funding_record(time_ms=BOUNDARY + 1),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(wrong_market, FundingGap)
    assert wrong_market.reason == "FUNDING_MARKET_MISMATCH"
    assert isinstance(wrong_time, FundingGap)
    assert wrong_time.reason == "FUNDING_TIME_MISMATCH"


def test_oracle_must_be_pre_boundary_and_fresh() -> None:
    future_oracle = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(received_ms=BOUNDARY + 1),
        funding_record(),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(),
    )
    stale_oracle = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(received_ms=BOUNDARY - 5_001),
        funding_record(),
        now_ms=BOUNDARY + 2_000,
        config=PaperExecutionConfig(max_asset_ctx_age_ms=5_000),
    )

    assert isinstance(future_oracle, FundingGap)
    assert future_oracle.reason == "ORACLE_AFTER_BOUNDARY"
    assert isinstance(stale_oracle, FundingGap)
    assert stale_oracle.reason == "ORACLE_CONTEXT_STALE"


def test_missing_evidence_is_gap_then_becomes_inconsistent_after_grace() -> None:
    config = PaperExecutionConfig(funding_reconciliation_grace_ms=300_000)
    within_grace = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(),
        None,
        now_ms=BOUNDARY + 299_999,
        config=config,
    )
    expired = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        oracle_ctx(),
        None,
        now_ms=BOUNDARY + 300_000,
        config=config,
    )

    assert isinstance(within_grace, FundingGap)
    assert within_grace.account_inconsistent is False
    assert isinstance(expired, FundingGap)
    assert expired.account_inconsistent is True
    assert expired.reason == "FUNDING_RECORD_MISSING"


def test_missing_oracle_is_never_interpolated_from_other_sources() -> None:
    result = reconcile_funding_boundary(
        position(),
        BOUNDARY,
        None,
        funding_record(),
        now_ms=BOUNDARY + 300_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(result, FundingGap)
    assert result.reason == "ORACLE_CONTEXT_MISSING"
    assert result.account_inconsistent is True
