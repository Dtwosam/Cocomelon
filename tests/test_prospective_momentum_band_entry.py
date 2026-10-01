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
from cocomelon.research.prospective_momentum_band_entry import (
    CANDIDATE_ID,
    EMBARGO_MS,
    MAX_SIGNED_DAY_RETURN,
    MIN_SIGNED_RETURN_1H,
    ProspectiveMomentumBandEntryError,
    ProspectiveMomentumBandEntryState,
    prospective_momentum_band_entry_summary,
)


def _feature(
    market: str,
    *,
    as_of_ms: int,
    return_1h: str | None,
    day_return: str | None,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=(
            None
            if day_return is None
            else Decimal(day_return)
        ),
        funding=Decimal("0"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=None,
        return_15m=None,
        return_1h=(
            None
            if return_1h is None
            else Decimal(return_1h)
        ),
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
        provenance=("test",),
    )


def _trade(
    suffix: str,
    *,
    market: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
    feature_snapshot_id: str,
    exit_reason: str = "MARK_STOP_TRIGGERED",
    hold_ms: int = 60_000,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    entry = Decimal("100")
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + hold_ms,
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
        holding_duration_ms=hold_ms,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason=exit_reason,
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _record(
    store: LearningFeatureSnapshotStore,
    market: str,
    *,
    as_of_ms: int,
    return_1h: str | None,
    day_return: str | None,
) -> str:
    snapshot = _feature(
        market,
        as_of_ms=as_of_ms,
        return_1h=return_1h,
        day_return=day_return,
    )
    store.record(snapshot)
    return snapshot.snapshot_id


def test_momentum_band_state_round_trip_locks_rule() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=123)
    assert state.started_at_ms == 123 + EMBARGO_MS
    assert state.candidate_id == CANDIDATE_ID
    rule = state.payload()["rule"]
    assert isinstance(rule, dict)
    assert rule["min_signed_return_1h"] == str(
        MIN_SIGNED_RETURN_1H
    )
    assert rule["max_signed_day_return"] == str(
        MAX_SIGNED_DAY_RETURN
    )
    restored = ProspectiveMomentumBandEntryState.from_payload(
        state.payload()
    )
    assert restored == state

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["min_signed_return_1h"] = "0.01"
    with pytest.raises(
        ProspectiveMomentumBandEntryError,
        match="frozen candidate",
    ):
        ProspectiveMomentumBandEntryState.from_payload(payload)


def test_zero_strike_rule_blocks_weak_and_overextended_entries(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    start = EMBARGO_MS + 1_000_000
    state = ProspectiveMomentumBandEntryState(
        frozen_at_ms=start - EMBARGO_MS
    )
    weak_id = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.005",
        day_return="0.04",
    )
    extended_id = _record(
        store,
        "ETH",
        as_of_ms=start + 119_999,
        return_1h="0.03",
        day_return="0.12",
    )
    pass_id = _record(
        store,
        "BTC",
        as_of_ms=start + 239_999,
        return_1h="0.02",
        day_return="0.08",
    )
    trades = (
        _trade(
            "weak",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=start,
            pnl="-5",
            feature_snapshot_id=weak_id,
        ),
        _trade(
            "extended",
            market="ETH",
            direction=Direction.LONG,
            opened_at_ms=start + 120_000,
            pnl="-6",
            feature_snapshot_id=extended_id,
        ),
        _trade(
            "pass",
            market="BTC",
            direction=Direction.LONG,
            opened_at_ms=start + 240_000,
            pnl="4",
            feature_snapshot_id=pass_id,
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
    )

    result = prospective_momentum_band_entry_summary(
        trades,
        store,
        state,
    )

    assert result["prospective_closed_trades"] == 3
    assert result["blocked_trades"] == 2
    assert result["blocked_losses"] == 2
    assert result["admitted_trades"] == 1
    assert result["blocked_net_pnl"] == "-11"
    assert result["candidate_net_pnl"] == "4"
    assert result["candidate_net_r"] == "0.4"
    assert result["delta_net_pnl"] == "11"
    assert result["delta_net_r"] == "1.1"


def test_rule_is_direction_normalized(tmp_path: Path) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    start = EMBARGO_MS + 2_000_000
    state = ProspectiveMomentumBandEntryState(
        frozen_at_ms=start - EMBARGO_MS
    )
    good_long = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.02",
        day_return="0.08",
    )
    good_short = _record(
        store,
        "ETH",
        as_of_ms=start + 119_999,
        return_1h="-0.02",
        day_return="-0.08",
    )
    bad_short = _record(
        store,
        "BTC",
        as_of_ms=start + 239_999,
        return_1h="0.02",
        day_return="-0.08",
    )
    trades = (
        _trade(
            "long",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=start,
            pnl="2",
            feature_snapshot_id=good_long,
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "short-good",
            market="ETH",
            direction=Direction.SHORT,
            opened_at_ms=start + 120_000,
            pnl="3",
            feature_snapshot_id=good_short,
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "short-bad",
            market="BTC",
            direction=Direction.SHORT,
            opened_at_ms=start + 240_000,
            pnl="-4",
            feature_snapshot_id=bad_short,
        ),
    )

    result = prospective_momentum_band_entry_summary(
        trades,
        store,
        state,
    )

    assert result["blocked_trades"] == 1
    details = result["decision_details"]
    assert isinstance(details, dict)
    assert details[trades[0].trade_id]["decision"] == "ADMIT"
    assert details[trades[1].trade_id]["decision"] == "ADMIT"
    assert details[trades[2].trade_id]["decision"] == "BLOCK"


def test_nonzero_strike_bypasses_momentum_band(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    start = EMBARGO_MS + 3_000_000
    state = ProspectiveMomentumBandEntryState(
        frozen_at_ms=start - EMBARGO_MS
    )
    pass_id = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.02",
        day_return="0.08",
    )
    weak_id = _record(
        store,
        "SOL",
        as_of_ms=start + 119_999,
        return_1h="0.001",
        day_return="0.02",
    )
    trades = (
        _trade(
            "first-loss",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=start,
            pnl="-5",
            feature_snapshot_id=pass_id,
        ),
        _trade(
            "bypass",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=start + 120_000,
            pnl="3",
            feature_snapshot_id=weak_id,
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "zero-again",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=start + 240_000,
            pnl="-4",
            feature_snapshot_id=weak_id,
        ),
    )

    result = prospective_momentum_band_entry_summary(
        trades,
        store,
        state,
    )

    strikes = result["decision_prior_strikes"]
    assert isinstance(strikes, dict)
    assert strikes[trades[0].trade_id] == 0
    assert strikes[trades[1].trade_id] == 1
    assert strikes[trades[2].trade_id] == 0
    assert result["nonzero_strike_bypass"] == 1
    assert result["blocked_trades"] == 1
    assert trades[2].trade_id in result["decision_details"]


def test_blocked_actual_outcome_does_not_create_strike(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    start = EMBARGO_MS + 4_000_000
    state = ProspectiveMomentumBandEntryState(
        frozen_at_ms=start - EMBARGO_MS
    )
    weak_a = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.001",
        day_return="0.02",
    )
    weak_b = _record(
        store,
        "SOL",
        as_of_ms=start + 119_999,
        return_1h="0.002",
        day_return="0.03",
    )
    trades = (
        _trade(
            "blocked-a",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=start,
            pnl="-5",
            feature_snapshot_id=weak_a,
        ),
        _trade(
            "blocked-b",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=start + 120_000,
            pnl="-6",
            feature_snapshot_id=weak_b,
        ),
    )

    result = prospective_momentum_band_entry_summary(
        trades,
        store,
        state,
    )

    strikes = result["decision_prior_strikes"]
    assert isinstance(strikes, dict)
    assert strikes[trades[0].trade_id] == 0
    assert strikes[trades[1].trade_id] == 0
    assert result["blocked_trades"] == 2


def test_missing_feature_fails_open_but_blocks_readiness(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    start = EMBARGO_MS + 5_000_000
    state = ProspectiveMomentumBandEntryState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trade = _trade(
        "missing",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=start,
        pnl="-5",
        feature_snapshot_id="0" * 24,
    )

    result = prospective_momentum_band_entry_summary(
        (trade,),
        store,
        state,
    )

    assert result["admitted_trades"] == 1
    assert result["blocked_trades"] == 0
    assert result["missing_feature_trades"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["feature_integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_pre_embargo_trades_receive_zero_credit(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    frozen = 6_000_000
    state = ProspectiveMomentumBandEntryState(
        frozen_at_ms=frozen
    )
    before_id = _record(
        store,
        "SOL",
        as_of_ms=frozen - 1,
        return_1h="0.001",
        day_return="0.02",
    )
    after_id = _record(
        store,
        "ETH",
        as_of_ms=state.started_at_ms - 1,
        return_1h="0.001",
        day_return="0.02",
    )
    trades = (
        _trade(
            "touched",
            market="SOL",
            direction=Direction.LONG,
            opened_at_ms=frozen,
            pnl="-5",
            feature_snapshot_id=before_id,
        ),
        _trade(
            "clean",
            market="ETH",
            direction=Direction.LONG,
            opened_at_ms=state.started_at_ms,
            pnl="-6",
            feature_snapshot_id=after_id,
        ),
    )

    result = prospective_momentum_band_entry_summary(
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
