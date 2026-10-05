from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_range_compression_entry import (
    CANDIDATE_ID,
    EMBARGO_MS,
    MAX_RANGE_EXPANSION_15M,
    ProspectiveRangeCompressionEntryError,
    ProspectiveRangeCompressionEntryState,
    prospective_range_compression_entry_summary,
    prospective_range_compression_snapshot_decision,
)


def _feature(
    market: str,
    *,
    as_of_ms: int,
    range_expansion_15m: str | None,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=Decimal("0"),
        funding=Decimal("0"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("0"),
        return_15m=Decimal("0"),
        return_1h=Decimal("0"),
        return_4h=Decimal("0"),
        realized_vol_15m=Decimal("0.01"),
        range_expansion_15m=(
            None
            if range_expansion_15m is None
            else Decimal(range_expansion_15m)
        ),
        relative_volume_15m=Decimal("1"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0"),
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _record(
    store: LearningFeatureSnapshotStore,
    market: str,
    *,
    as_of_ms: int,
    range_expansion_15m: str | None,
) -> str:
    snapshot = _feature(
        market,
        as_of_ms=as_of_ms,
        range_expansion_15m=range_expansion_15m,
    )
    store.record(snapshot)
    return snapshot.snapshot_id


def _trade(
    suffix: str,
    *,
    market: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
    feature_snapshot_id: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    entry = Decimal("100")
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        feature_snapshot_id=feature_snapshot_id,
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-{suffix}", f"close-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=(
            entry + net
            if direction is Direction.LONG
            else entry - net
        ),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_state_round_trip_locks_range_compression_rule() -> None:
    state = ProspectiveRangeCompressionEntryState(frozen_at_ms=123)
    assert state.started_at_ms == 123 + EMBARGO_MS
    assert state.candidate_id == CANDIDATE_ID

    rule = state.payload()["rule"]
    assert isinstance(rule, dict)
    assert rule["max_range_expansion_15m"] == str(
        MAX_RANGE_EXPANSION_15M
    )
    assert rule["block_if"] == "range_expansion_15m_at_or_below_max"
    assert rule["historical_discovery_only"] is True

    assert ProspectiveRangeCompressionEntryState.from_payload(
        state.payload()
    ) == state

    payload = state.payload()
    raw_rule = payload["rule"]
    assert isinstance(raw_rule, dict)
    raw_rule["max_range_expansion_15m"] = "0.81"
    with pytest.raises(
        ProspectiveRangeCompressionEntryError,
        match="frozen candidate",
    ):
        ProspectiveRangeCompressionEntryState.from_payload(payload)


def test_range_compression_rule_uses_frozen_threshold(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    for index, (value, expected) in enumerate(
        (("0.79", "BLOCK"), ("0.80", "BLOCK"), ("0.81", "ADMIT"))
    ):
        timestamp_ms = 10_000 + index
        snapshot_id = _record(
            store,
            "SOL",
            as_of_ms=timestamp_ms - 1,
            range_expansion_15m=value,
        )
        detail = prospective_range_compression_snapshot_decision(
            store,
            market=MarketId("", "SOL"),
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            timestamp_ms=timestamp_ms,
            feature_snapshot_id=snapshot_id,
        )
        assert detail["decision"] == expected
        assert detail["range_expansion_15m"] == value


def test_missing_range_feature_fails_open_but_blocks_readiness(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(frozen_at_ms=100)
    opened_at_ms = state.started_at_ms
    snapshot_id = _record(
        store,
        "SOL",
        as_of_ms=opened_at_ms - 1,
        range_expansion_15m=None,
    )
    trade = _trade(
        "missing",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        pnl="-5",
        feature_snapshot_id=snapshot_id,
    )

    result = prospective_range_compression_entry_summary(
        (trade,),
        store,
        state,
    )

    assert result["admitted_trades"] == 1
    assert result["missing_feature_trades"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["feature_integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_pre_embargo_trade_receives_zero_credit(tmp_path: Path) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(frozen_at_ms=1_000)
    touched_id = _record(
        store,
        "SOL",
        as_of_ms=state.frozen_at_ms - 1,
        range_expansion_15m="0.50",
    )
    clean_id = _record(
        store,
        "ETH",
        as_of_ms=state.started_at_ms - 1,
        range_expansion_15m="0.50",
    )
    trades = (
        _trade(
            "touched",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=state.frozen_at_ms,
            pnl="-5",
            feature_snapshot_id=touched_id,
        ),
        _trade(
            "clean",
            market="ETH",
            direction=Direction.SHORT,
            opened_at_ms=state.started_at_ms,
            pnl="-6",
            feature_snapshot_id=clean_id,
        ),
    )

    result = prospective_range_compression_entry_summary(
        trades,
        store,
        state,
    )

    assert result["prospective_closed_trades"] == 1
    assert result["blocked_trades"] == 1
    details = result["decision_details"]
    assert isinstance(details, dict)
    assert trades[0].trade_id not in details
    assert trades[1].trade_id in details


def _economic_sample(
    store: LearningFeatureSnapshotStore,
    *,
    admitted_pnl: str,
) -> tuple[
    tuple[TradeJournalEntry, ...],
    ProspectiveRangeCompressionEntryState,
]:
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=2_000_000
    )
    start = state.started_at_ms
    trades: list[TradeJournalEntry] = []
    markets = ("SOL", "ETH", "BTC", "ENA")
    for index in range(30):
        direction = (
            Direction.LONG
            if index % 2 == 0
            else Direction.SHORT
        )
        market = markets[index % len(markets)]
        opened_at_ms = start + index * 120_000
        blocked = index < 10
        snapshot_id = _record(
            store,
            market,
            as_of_ms=opened_at_ms - 1,
            range_expansion_15m=("0.70" if blocked else "1.10"),
        )
        trades.append(
            _trade(
                f"economic-{index}",
                market=market,
                direction=direction,
                opened_at_ms=opened_at_ms,
                pnl="-1" if blocked else admitted_pnl,
                feature_snapshot_id=snapshot_id,
            )
        )
    return tuple(trades), state


def test_range_candidate_requires_profitable_robust_economics(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    trades, state = _economic_sample(store, admitted_pnl="2")

    result = prospective_range_compression_entry_summary(
        trades,
        store,
        state,
    )

    assert result["prospective_closed_trades"] == 30
    assert result["blocked_trades"] == 10
    assert result["admitted_trades"] == 20
    assert result["candidate_net_pnl"] == "40"
    assert result["delta_net_pnl"] == "10"
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["sample_complete"] is True
    assert readiness["candidate_profitable"] is True
    assert readiness["improvement_positive"] is True
    assert readiness["single_trade_robust"] is True
    assert readiness["single_market_robust"] is True
    assert readiness["ready_for_review"] is True


def test_range_candidate_rejects_less_bad_losing_economics(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    trades, state = _economic_sample(store, admitted_pnl="-1")

    result = prospective_range_compression_entry_summary(
        trades,
        store,
        state,
    )

    assert result["candidate_net_pnl"] == "-20"
    assert result["delta_net_pnl"] == "10"
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["sample_complete"] is True
    assert readiness["candidate_profitable"] is False
    assert readiness["improvement_positive"] is True
    assert readiness["economics_positive"] is False
    assert readiness["ready_for_review"] is False
