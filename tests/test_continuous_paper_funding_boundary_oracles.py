from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.research.continuous_paper_funding_boundary_oracles import (
    FUNDING_ORACLE_CAPTURE_LEAD_MS,
    ContinuousPaperFundingBoundaryOracleError,
    ContinuousPaperFundingBoundaryOracleStore,
    next_funding_boundary_ms,
)


def _snapshot(
    market: str,
    *,
    received_at_ms: int,
    oracle_px: str | None = "100",
) -> PerpMarketSnapshot:
    market_id = MarketId(dex="", coin=market)
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market_id,
            wire_name=market,
            sz_decimals=2,
            max_leverage=5,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market_id,
            mark_px=Decimal("100"),
            mid_px=Decimal("100"),
            oracle_px=(
                None if oracle_px is None else Decimal(oracle_px)
            ),
            funding=Decimal("0.0001"),
            open_interest=Decimal("1000"),
            day_ntl_vlm=Decimal("1000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def test_next_funding_boundary_is_strictly_after_now() -> None:
    hour = 3_600_000
    assert next_funding_boundary_ms(0) == hour
    assert next_funding_boundary_ms(hour - 1) == hour
    assert next_funding_boundary_ms(hour) == 2 * hour
    assert FUNDING_ORACLE_CAPTURE_LEAD_MS < 5_000


def test_boundary_oracle_store_records_only_valid_pre_boundary_prices(
    tmp_path: Path,
) -> None:
    boundary = 3_600_000
    store = ContinuousPaperFundingBoundaryOracleStore(
        tmp_path / "funding-oracles",
        protocol_started_at_ms=1_000,
        max_oracle_age_ms=5_000,
    )
    result = store.record_attempt(
        boundary_ms=boundary,
        snapshots={
            "BTC": _snapshot(
                "BTC",
                received_at_ms=boundary - 3_000,
                oracle_px="65000",
            ),
            "ETH": _snapshot(
                "ETH",
                received_at_ms=boundary - 3_000,
                oracle_px=None,
            ),
        },
        completed_at_ms=boundary - 3_000,
    )

    assert result.outcome == "captured"
    assert result.recorded_markets == 1
    evidence = store.load("BTC", boundary)
    assert evidence is not None
    assert evidence.market == "BTC"
    assert evidence.boundary_ms == boundary
    assert evidence.oracle_px == Decimal("65000")
    assert evidence.observed_at_ms == boundary - 3_000
    assert evidence.oracle_age_ms == 3_000
    assert store.load("ETH", boundary) is None
    assert store.attempt_count == 1
    assert store.captured_boundary_count == 1
    assert store.missed_boundary_count == 0
    assert store.record_count == 1
    assert len(store.state_digest) == 64

    restored = ContinuousPaperFundingBoundaryOracleStore(
        tmp_path / "funding-oracles",
        protocol_started_at_ms=999_999,
        max_oracle_age_ms=5_000,
    )
    assert restored.protocol_started_at_ms == 1_000
    assert restored.load("BTC", boundary) == evidence


def test_late_boundary_oracle_attempt_is_durable_miss(
    tmp_path: Path,
) -> None:
    boundary = 3_600_000
    store = ContinuousPaperFundingBoundaryOracleStore(
        tmp_path / "funding-oracles",
        protocol_started_at_ms=1_000,
        max_oracle_age_ms=5_000,
    )
    result = store.record_attempt(
        boundary_ms=boundary,
        snapshots={
            "BTC": _snapshot(
                "BTC",
                received_at_ms=boundary + 1,
                oracle_px="65000",
            )
        },
        completed_at_ms=boundary + 1,
    )

    assert result.outcome == "missed"
    assert result.reason == "response_after_boundary"
    assert result.recorded_markets == 0
    assert store.record_count == 0
    assert store.missed_boundary_count == 1


def test_too_early_boundary_oracle_attempt_is_durable_miss(
    tmp_path: Path,
) -> None:
    boundary = 3_600_000
    store = ContinuousPaperFundingBoundaryOracleStore(
        tmp_path / "funding-oracles",
        protocol_started_at_ms=1_000,
        max_oracle_age_ms=5_000,
    )
    result = store.record_attempt(
        boundary_ms=boundary,
        snapshots={
            "BTC": _snapshot(
                "BTC",
                received_at_ms=boundary - 5_001,
                oracle_px="65000",
            )
        },
        completed_at_ms=boundary - 5_001,
    )

    assert result.outcome == "missed"
    assert result.reason == "response_too_early"
    assert store.record_count == 0


def test_boundary_attempt_is_content_addressed_and_conflict_detecting(
    tmp_path: Path,
) -> None:
    boundary = 3_600_000
    store = ContinuousPaperFundingBoundaryOracleStore(
        tmp_path / "funding-oracles",
        protocol_started_at_ms=1_000,
        max_oracle_age_ms=5_000,
    )
    first = {
        "BTC": _snapshot(
            "BTC",
            received_at_ms=boundary - 3_000,
            oracle_px="65000",
        )
    }
    store.record_attempt(
        boundary_ms=boundary,
        snapshots=first,
        completed_at_ms=boundary - 3_000,
    )
    duplicate = store.record_attempt(
        boundary_ms=boundary,
        snapshots=first,
        completed_at_ms=boundary - 3_000,
    )
    assert duplicate.outcome == "captured"
    assert store.attempt_count == 1

    conflicting = {
        "BTC": _snapshot(
            "BTC",
            received_at_ms=boundary - 2_000,
            oracle_px="66000",
        )
    }
    with pytest.raises(
        ContinuousPaperFundingBoundaryOracleError,
        match="FUNDING_BOUNDARY_ORACLE_ATTEMPT_CONFLICT",
    ):
        store.record_attempt(
            boundary_ms=boundary,
            snapshots=conflicting,
            completed_at_ms=boundary - 2_000,
        )
