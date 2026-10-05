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
from cocomelon.research.prospective_range_compression_entry import (
    EMBARGO_MS,
    ProspectiveRangeCompressionEntryState,
)
from cocomelon.research.prospective_range_compression_entry_evidence import (
    ProspectiveRangeCompressionEvidenceError,
    update_range_compression_evidence,
    validate_range_compression_evidence,
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
        provenance=("range-evidence-test",),
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


def _update(
    trades: tuple[TradeJournalEntry, ...],
    store: LearningFeatureSnapshotStore,
    state: ProspectiveRangeCompressionEntryState,
    *,
    previous: dict[str, object] | None = None,
    run_id: int = 100,
    digest_char: str = "a",
) -> dict[str, object]:
    return update_range_compression_evidence(
        trades,
        store,
        state,
        previous=previous,
        source_paper_run_id=run_id,
        source_paper_run_attempt=1,
        source_head_sha=digest_char * 40,
        source_artifact_name=f"source-{run_id}",
        source_artifact_digest="sha256:" + digest_char * 64,
    )


def test_range_evidence_binds_features_and_appends(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=1_000_000
    )
    start = state.started_at_ms
    blocked_id = _record(
        store,
        "SOL",
        as_of_ms=start - 1,
        range_expansion_15m="0.70",
    )
    admitted_id = _record(
        store,
        "ETH",
        as_of_ms=start + 119_999,
        range_expansion_15m="1.10",
    )
    blocked = _trade(
        "blocked",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=start,
        pnl="-5",
        feature_snapshot_id=blocked_id,
    )
    admitted = _trade(
        "admitted",
        market="ETH",
        direction=Direction.SHORT,
        opened_at_ms=start + 120_000,
        pnl="4",
        feature_snapshot_id=admitted_id,
    )

    first = _update((blocked, admitted), store, state)
    assert first["row_count"] == 2
    assert first["previous_row_count"] == 0
    assert first["new_row_count"] == 2
    rows = first["rows"]
    assert isinstance(rows, list)
    assert rows[0]["decision"] == "BLOCK"
    assert rows[0]["range_expansion_15m"] == "0.70"
    assert rows[1]["decision"] == "ADMIT"
    assert rows[1]["range_expansion_15m"] == "1.10"

    third_id = _record(
        store,
        "BTC",
        as_of_ms=start + 239_999,
        range_expansion_15m="0.80",
    )
    third = _trade(
        "third",
        market="BTC",
        direction=Direction.LONG,
        opened_at_ms=start + 240_000,
        pnl="-3",
        feature_snapshot_id=third_id,
    )
    extended = _update(
        (blocked, admitted, third),
        store,
        state,
        previous=first,
        run_id=101,
        digest_char="b",
    )
    assert extended["row_count"] == 3
    assert extended["previous_row_count"] == 2
    assert extended["new_row_count"] == 1
    assert extended["prior_evidence_sha256"] == first["evidence_sha256"]
    assert len(extended["source_history"]) == 2
    extended_rows = extended["rows"]
    assert isinstance(extended_rows, list)
    assert extended_rows[2]["decision"] == "BLOCK"
    assert extended_rows[2]["range_expansion_15m"] == "0.80"


def test_range_evidence_records_missing_feature_fail_open(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=2_000_000
    )
    trade = _trade(
        "missing",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=state.started_at_ms,
        pnl="-5",
        feature_snapshot_id="0" * 24,
    )

    evidence = _update((trade,), store, state)
    rows = evidence["rows"]
    assert isinstance(rows, list)
    row = rows[0]
    assert row["decision"] == "ADMIT"
    assert row["reason"] == "missing_feature_fail_open"
    assert row["feature_status"] == "missing"
    assert row["feature_record_sha256"] is None
    summary = evidence["summary"]
    assert isinstance(summary, dict)
    readiness = summary["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["feature_integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_range_evidence_duplicate_source_is_idempotent(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=3_000_000
    )
    feature_id = _record(
        store,
        "SOL",
        as_of_ms=state.started_at_ms - 1,
        range_expansion_15m="1.20",
    )
    trade = _trade(
        "same",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=state.started_at_ms,
        pnl="3",
        feature_snapshot_id=feature_id,
    )
    first = _update((trade,), store, state)
    repeated = _update(
        (trade,),
        store,
        state,
        previous=first,
    )
    assert repeated == validate_range_compression_evidence(first)


def test_range_evidence_rejects_disappearing_prior_trade(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=4_000_000
    )
    feature_id = _record(
        store,
        "SOL",
        as_of_ms=state.started_at_ms - 1,
        range_expansion_15m="1.20",
    )
    trade = _trade(
        "prior",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=state.started_at_ms,
        pnl="3",
        feature_snapshot_id=feature_id,
    )
    first = _update((trade,), store, state)

    with pytest.raises(
        ProspectiveRangeCompressionEvidenceError,
        match="prior evidence trade disappeared",
    ):
        _update(
            (),
            store,
            state,
            previous=first,
            run_id=101,
            digest_char="b",
        )


def test_range_evidence_rejects_source_rollback(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=4_500_000
    )
    first = _update(
        (),
        store,
        state,
        run_id=200,
        digest_char="c",
    )

    with pytest.raises(
        ProspectiveRangeCompressionEvidenceError,
        match="source run identity regressed",
    ):
        _update(
            (),
            store,
            state,
            previous=first,
            run_id=199,
            digest_char="d",
        )


def test_range_evidence_rejects_row_tamper(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=5_000_000
    )
    feature_id = _record(
        store,
        "SOL",
        as_of_ms=state.started_at_ms - 1,
        range_expansion_15m="0.70",
    )
    trade = _trade(
        "tamper",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=state.started_at_ms,
        pnl="-3",
        feature_snapshot_id=feature_id,
    )
    evidence = _update((trade,), store, state)
    raw = json.loads(json.dumps(evidence))
    raw["rows"][0]["range_expansion_15m"] = "1.20"

    with pytest.raises(
        ProspectiveRangeCompressionEvidenceError,
        match="range decision does not match frozen threshold",
    ):
        validate_range_compression_evidence(raw)


def test_range_evidence_rejects_frozen_state_drift(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    state = ProspectiveRangeCompressionEntryState(
        frozen_at_ms=6_000_000
    )
    evidence = _update((), store, state)
    raw = json.loads(json.dumps(evidence))
    raw["state"]["rule"]["max_range_expansion_15m"] = "0.81"

    with pytest.raises(
        ProspectiveRangeCompressionEvidenceError,
        match="state is invalid",
    ):
        validate_range_compression_evidence(raw)
