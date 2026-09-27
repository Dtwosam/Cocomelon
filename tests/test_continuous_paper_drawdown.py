from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.research.continuous_paper_drawdown import (
    ContinuousPaperDrawdownError,
    ContinuousPaperDrawdownTracker,
    drawdown_summary,
    realized_closed_trade_drawdown,
)


def _trade(
    trade_id: str,
    pnl: str,
    closed_at_ms: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=trade_id,
        net_pnl=Decimal(pnl),
        closed_at_ms=closed_at_ms,
    )


def test_sampled_drawdown_tracks_high_water_and_recovery() -> None:
    tracker = ContinuousPaperDrawdownTracker(
        started_at_ms=1_000,
    )
    tracker.observe(Decimal("100"), timestamp_ms=1_000)
    tracker.observe(Decimal("110"), timestamp_ms=2_000)
    tracker.observe(Decimal("99"), timestamp_ms=3_000)

    assert tracker.observation_count == 3
    assert tracker.peak_equity == Decimal("110")
    assert tracker.current_drawdown_fraction() == Decimal("0.1")
    assert tracker.current_drawdown_amount() == Decimal("11")
    assert tracker.max_drawdown_fraction == Decimal("0.1")
    assert tracker.max_drawdown_amount == Decimal("11")
    assert tracker.max_drawdown_peak_timestamp_ms == 2_000
    assert tracker.max_drawdown_trough_timestamp_ms == 3_000

    tracker.observe(Decimal("120"), timestamp_ms=4_000)
    assert tracker.peak_equity == Decimal("120")
    assert tracker.current_drawdown_fraction() == Decimal("0")
    assert tracker.max_drawdown_fraction == Decimal("0.1")


def test_drawdown_state_round_trip_preserves_watermark() -> None:
    tracker = ContinuousPaperDrawdownTracker(
        started_at_ms=1_000,
    )
    tracker.observe(Decimal("100"), timestamp_ms=1_000)
    tracker.observe(Decimal("90"), timestamp_ms=2_000)

    restored = ContinuousPaperDrawdownTracker.from_payload(
        tracker.state_payload()
    )

    assert restored.state_restored is True
    assert restored.observation_count == 2
    assert restored.peak_equity == Decimal("100")
    assert restored.last_equity == Decimal("90")
    assert restored.max_drawdown_fraction == Decimal("0.1")

    with pytest.raises(
        ContinuousPaperDrawdownError,
        match="time regressed",
    ):
        restored.observe(
            Decimal("95"),
            timestamp_ms=1_999,
        )


def test_realized_closed_trade_drawdown_is_chronological() -> None:
    trades = (
        _trade("third", "5", 3_000),
        _trade("first", "10", 1_000),
        _trade("second", "-20", 2_000),
    )

    result = realized_closed_trade_drawdown(
        trades,  # type: ignore[arg-type]
        starting_equity=Decimal("100"),
    )

    assert result["closed_trades"] == 3
    assert result["ending_realized_equity"] == "95"
    assert result["peak_realized_equity"] == "110"
    assert result["max_drawdown_amount"] == "20"
    assert Decimal(str(result["max_drawdown_fraction"])) == (
        Decimal("20") / Decimal("110")
    )
    assert result["max_drawdown_peak_timestamp_ms"] == 1_000
    assert result["max_drawdown_trough_timestamp_ms"] == 2_000


def test_drawdown_summary_keeps_sampled_and_realized_scopes_separate() -> None:
    tracker = ContinuousPaperDrawdownTracker(
        started_at_ms=10_000,
    )
    tracker.observe(Decimal("101"), timestamp_ms=10_000)
    tracker.observe(Decimal("99"), timestamp_ms=40_000)
    trades = (
        _trade("one", "-1", 20_000),
        _trade("two", "2", 30_000),
    )

    result = drawdown_summary(
        tracker,
        trades,  # type: ignore[arg-type]
        starting_equity=Decimal("100"),
        checkpoint_seconds=30,
    )

    sampled = result["sampled_account"]
    realized = result["realized_closed_trade"]
    assert isinstance(sampled, dict)
    assert isinstance(realized, dict)
    assert sampled["definition"] == (
        "prospective_runtime_checkpoint_equity"
    )
    assert sampled["checkpoint_seconds"] == 30
    assert sampled["observation_count"] == 2
    assert sampled["first_timestamp_ms"] == 10_000
    assert sampled["last_timestamp_ms"] == 40_000
    assert sampled["peak_timestamp_ms"] == 10_000
    assert sampled["mean_observation_interval_ms"] == 30_000
    assert sampled["max_drawdown_amount"] == "2"
    assert realized["ending_realized_equity"] == "101"
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
