from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import (
    FundingRate,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ContinuousPaperReplacementFundingError,
    ContinuousPaperReplacementFundingStore,
)

BOUNDARY = 3_600_000


def _market(name: str = "BTC") -> MarketId:
    return MarketId.from_wire_name("", name)


def _snapshot(
    *,
    market: str = "BTC",
    received_at_ms: int,
    oracle_px: str = "100",
) -> PerpMarketSnapshot:
    resolved = _market(market)
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=resolved,
            wire_name=resolved.wire_name,
            sz_decimals=3,
            max_leverage=20,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=resolved,
            mark_px=Decimal("100"),
            mid_px=Decimal("100"),
            oracle_px=Decimal(oracle_px),
            funding=Decimal("0.001"),
            open_interest=Decimal("10"),
            day_ntl_vlm=Decimal("1000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _rate(
    *,
    market: str = "BTC",
    time_ms: int = BOUNDARY,
    received_at_ms: int = BOUNDARY + 2_000,
    funding_rate: str = "0.001",
) -> FundingRate:
    return FundingRate(
        market=_market(market),
        time_ms=time_ms,
        funding_rate=Decimal(funding_rate),
        premium=Decimal("0.0002"),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _store(root: Path) -> ContinuousPaperReplacementFundingStore:
    return ContinuousPaperReplacementFundingStore(
        root,
        capture_started_at_ms=3_500_000,
        max_window_ms=3_800_000,
        max_oracle_age_ms=5_000,
        max_funding_capture_lag_ms=300_000,
    )


def test_funding_store_captures_exact_boundary_inputs(tmp_path: Path) -> None:
    store = _store(tmp_path / "funding")
    assert store.register(
        opportunity_id="opp-1",
        market="BTC",
        opportunity_timestamp_ms=3_590_000,
    ) is True
    requirements = store.required_boundaries()
    assert tuple(item.boundary_ms for item in requirements) == (
        3_600_000,
        7_200_000,
    )

    assert store.observe_snapshot(
        _snapshot(received_at_ms=BOUNDARY - 4_000)
    ) is True
    assert store.observe_snapshot(
        _snapshot(received_at_ms=BOUNDARY - 1_000, oracle_px="101")
    ) is True
    assert store.observe_snapshot(
        _snapshot(received_at_ms=BOUNDARY - 2_000, oracle_px="99")
    ) is False

    due = store.due_requests(now_ms=BOUNDARY + 2_000)
    assert len(due) == 1
    assert due[0].market == "BTC"
    assert due[0].boundary_ms == BOUNDARY
    assert store.capture(due[0], _rate()) is True

    restored = _store(tmp_path / "funding")
    evidence = restored.load("BTC", BOUNDARY)
    assert evidence is not None
    assert evidence.oracle_px == Decimal("101")
    assert evidence.oracle_observed_at_ms == BOUNDARY - 1_000
    assert evidence.oracle_age_ms == 1_000
    assert evidence.funding_rate == Decimal("0.001")
    assert evidence.funding_time_ms == BOUNDARY
    assert evidence.funding_received_at_ms == BOUNDARY + 2_000
    assert restored.registration_count == 1
    assert restored.required_boundary_count == 2
    assert restored.record_count == 1
    assert len(restored.state_digest) == 64


def test_funding_store_rejects_stale_or_post_boundary_oracle(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "funding")
    store.register(
        opportunity_id="opp-1",
        market="BTC",
        opportunity_timestamp_ms=3_590_000,
    )

    assert store.observe_snapshot(
        _snapshot(received_at_ms=BOUNDARY - 5_001)
    ) is False
    assert store.observe_snapshot(
        _snapshot(received_at_ms=BOUNDARY + 1)
    ) is False
    assert store.due_requests(now_ms=BOUNDARY + 2_000) == ()
    assert store.pending_count(now_ms=BOUNDARY + 2_000) == 2


def test_funding_store_fails_closed_on_wrong_boundary_rate(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "funding")
    store.register(
        opportunity_id="opp-1",
        market="BTC",
        opportunity_timestamp_ms=3_590_000,
    )
    store.observe_snapshot(
        _snapshot(received_at_ms=BOUNDARY - 1_000)
    )
    request = store.due_requests(now_ms=BOUNDARY + 2_000)[0]

    with pytest.raises(
        ContinuousPaperReplacementFundingError,
        match="funding rate boundary mismatch",
    ):
        store.capture(
            request,
            _rate(time_ms=BOUNDARY + 2_000),
        )


def test_funding_store_quarantines_pre_protocol_opportunities(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "funding")

    with pytest.raises(
        ContinuousPaperReplacementFundingError,
        match="predates funding capture protocol",
    ):
        store.register(
            opportunity_id="legacy",
            market="BTC",
            opportunity_timestamp_ms=3_400_000,
        )


def test_funding_store_marks_expired_requirement_missed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "funding")
    store.register(
        opportunity_id="opp-1",
        market="BTC",
        opportunity_timestamp_ms=3_590_000,
    )
    assert store.missed_count(
        now_ms=BOUNDARY + 300_001
    ) == 1
    assert store.pending_count(
        now_ms=BOUNDARY + 300_001
    ) == 1
