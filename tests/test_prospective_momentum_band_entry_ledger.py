from __future__ import annotations

import json
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
    EMBARGO_MS,
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_momentum_band_entry_ledger import (
    ProspectiveMomentumBandEntryLedgerError,
    update_momentum_band_ledger,
    validate_momentum_band_ledger,
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
        provenance=("ledger-test",),
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


def _trade(
    suffix: str,
    *,
    market: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
    feature_snapshot_id: str,
    exit_reason: str = "MARK_STOP_TRIGGERED",
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
        exit_reason=exit_reason,
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _state() -> tuple[ProspectiveMomentumBandEntryState, int]:
    start = EMBARGO_MS + 1_000_000
    return (
        ProspectiveMomentumBandEntryState(
            frozen_at_ms=start - EMBARGO_MS
        ),
        start,
    )


def _update(
    trades: tuple[TradeJournalEntry, ...],
    store: LearningFeatureSnapshotStore,
    state: ProspectiveMomentumBandEntryState,
    *,
    previous: dict[str, object] | None = None,
    run_id: int = 10,
    digest: str = "sha256:" + "a" * 64,
) -> dict[str, object]:
    return update_momentum_band_ledger(
        trades,
        store,
        state,
        previous=previous,
        source_paper_run_id=run_id,
        source_paper_run_attempt=1,
        source_artifact_name=f"source-{run_id}",
        source_artifact_digest=digest,
    )


def test_momentum_ledger_binds_feature_identity_and_appends(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state, start = _state()
    weak_id = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.005",
        day_return="0.04",
    )
    good_id = _record(
        store,
        "ETH",
        as_of_ms=start + 119_999,
        return_1h="-0.02",
        day_return="-0.08",
    )
    first = _trade(
        "weak",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=start,
        pnl="-5",
        feature_snapshot_id=weak_id,
    )
    second = _trade(
        "good-short",
        market="ETH",
        direction=Direction.SHORT,
        opened_at_ms=start + 120_000,
        pnl="4",
        feature_snapshot_id=good_id,
        exit_reason="OPPOSITE_FRESH_THESIS",
    )

    first_ledger = _update(
        (first, second),
        store,
        state,
    )
    assert first_ledger["row_count"] == 2
    assert first_ledger["previous_row_count"] == 0
    assert first_ledger["new_row_count"] == 2

    rows = first_ledger["rows"]
    assert isinstance(rows, tuple)
    blocked = rows[0]
    admitted = rows[1]
    assert blocked["decision"] == "BLOCK"
    assert blocked["reason"] == "momentum_band"
    assert blocked["feature_status"] == "complete"
    verified = store.load(weak_id)
    assert verified is not None
    assert blocked["feature_record_sha256"] == verified.record_sha256
    assert blocked["signed_return_1h"] == "0.005"
    assert blocked["signed_day_return"] == "0.04"
    assert admitted["decision"] == "ADMIT"
    assert admitted["signed_return_1h"] == "0.02"
    assert admitted["signed_day_return"] == "0.08"

    third_id = _record(
        store,
        "BTC",
        as_of_ms=start + 239_999,
        return_1h="0.001",
        day_return="0.02",
    )
    third = _trade(
        "new-block",
        market="BTC",
        direction=Direction.LONG,
        opened_at_ms=start + 240_000,
        pnl="-6",
        feature_snapshot_id=third_id,
    )
    extended = _update(
        (first, second, third),
        store,
        state,
        previous=first_ledger,
        run_id=11,
        digest="sha256:" + "b" * 64,
    )

    assert extended["row_count"] == 3
    assert extended["previous_row_count"] == 2
    assert extended["new_row_count"] == 1
    assert extended["prior_ledger_sha256"] == first_ledger["ledger_sha256"]
    extended_rows = extended["rows"]
    assert isinstance(extended_rows, tuple)
    assert extended_rows[:2] == rows
    assert len(extended["source_history"]) == 2


def test_momentum_ledger_records_missing_feature_fail_open(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state, start = _state()
    trade = _trade(
        "missing",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=start,
        pnl="-5",
        feature_snapshot_id="0" * 24,
    )

    ledger = _update((trade,), store, state)

    rows = ledger["rows"]
    assert isinstance(rows, tuple)
    row = rows[0]
    assert row["candidate_admitted"] is True
    assert row["reason"] == "missing_feature_fail_open"
    assert row["feature_status"] == "missing"
    assert row["feature_record_sha256"] is None
    assert row["signed_return_1h"] is None
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    readiness = summary["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["feature_integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_momentum_ledger_duplicate_source_is_idempotent(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state, start = _state()
    feature_id = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.02",
        day_return="0.08",
    )
    trade = _trade(
        "same",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=start,
        pnl="3",
        feature_snapshot_id=feature_id,
        exit_reason="OPPOSITE_FRESH_THESIS",
    )
    first = _update((trade,), store, state)

    repeated = _update(
        (trade,),
        store,
        state,
        previous=first,
    )

    assert repeated == validate_momentum_band_ledger(first)


def test_momentum_ledger_rejects_disappearing_prior_row(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state, start = _state()
    feature_id = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.02",
        day_return="0.08",
    )
    trade = _trade(
        "prior",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=start,
        pnl="3",
        feature_snapshot_id=feature_id,
        exit_reason="OPPOSITE_FRESH_THESIS",
    )
    first = _update((trade,), store, state)

    with pytest.raises(
        ProspectiveMomentumBandEntryLedgerError,
        match="opening row disappeared",
    ):
        _update(
            (),
            store,
            state,
            previous=first,
            run_id=11,
            digest="sha256:" + "b" * 64,
        )


def test_momentum_ledger_rejects_row_feature_digest_tamper(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state, start = _state()
    feature_id = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        return_1h="0.02",
        day_return="0.08",
    )
    trade = _trade(
        "tamper",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=start,
        pnl="3",
        feature_snapshot_id=feature_id,
        exit_reason="OPPOSITE_FRESH_THESIS",
    )
    ledger = _update((trade,), store, state)
    raw = json.loads(json.dumps(ledger))
    raw["rows"][0]["feature_record_sha256"] = "f" * 64

    with pytest.raises(
        ProspectiveMomentumBandEntryLedgerError,
        match="row digest mismatch",
    ):
        validate_momentum_band_ledger(raw)


def test_momentum_ledger_rejects_frozen_rule_drift(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state, _start = _state()
    ledger = _update((), store, state)
    raw = json.loads(json.dumps(ledger))
    raw["rule"]["min_signed_return_1h"] = "0.01"

    with pytest.raises(
        ProspectiveMomentumBandEntryLedgerError,
        match="rule drift",
    ):
        validate_momentum_band_ledger(raw)
