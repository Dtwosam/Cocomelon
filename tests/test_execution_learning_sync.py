from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon import execution_learning_sync_cli
from cocomelon.domain import features, journal, market, replay, strategy
from cocomelon.journal import store as journal_store
from cocomelon.research import learning_feature_snapshots, outcome_learning

MARKET = market.MarketId("", "HYPE")


def _snapshot(*, as_of_ms: int = 9_000, market: market.MarketId = MARKET) -> features.FeatureSnapshot:
    return features.FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms - 100,
        schema_version=1,
        day_return=Decimal("0.04"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("5000000"),
        oi_change_fraction=Decimal("0.03"),
        funding_change=Decimal("0.00001"),
        mark_oracle_dislocation_bps=Decimal("1.5"),
        return_5m=Decimal("0.01"),
        return_15m=Decimal("0.02"),
        return_1h=Decimal("0.03"),
        return_4h=Decimal("0.05"),
        realized_vol_15m=Decimal("0.008"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.4"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("250000"),
        ask_depth_25bps=Decimal("230000"),
        book_imbalance=Decimal("0.04"),
        book_age_ms=50,
        trend_regime=features.TrendRegime.UP,
        volatility_regime=features.VolatilityRegime.NORMAL,
        provenance=("hyperliquid-mainnet-info",),
    )


def _trade(snapshot: features.FeatureSnapshot, *, run_id: str = "run-1") -> journal.TradeJournalEntry:
    return journal.TradeJournalEntry(
        market=MARKET,
        direction=strategy.Direction.LONG,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id=snapshot.snapshot_id,
        strategy_decision_id="strategy-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-open-1",
        opening_attempt_id="attempt-open-1",
        exit_plan_ids=("plan-close-1",),
        exit_attempt_ids=("attempt-close-1",),
        fill_ids=("fill-open-1", "fill-close-1"),
        position_action_ids=("action-close-1",),
        funding_event_ids=(),
        initial_stop=Decimal("95"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        filled_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.4545"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("9.0955"),
        entry_slippage_amount=Decimal("0.1"),
        exit_slippage_amount=Decimal("0.2"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.002"),
        holding_duration_ms=10_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.36382"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10009.0955"),
        exit_reason="exit_thesis",
        health_refs=("paper-state-healthy",),
        evidence_class=replay.EvidenceClass.MICROSTRUCTURE,
        replay_run_id=run_id,
    )


def _source(tmp_path, *, snapshot: features.FeatureSnapshot, run_id: str = "run-1"):
    journal_path = tmp_path / "journal.sqlite3"
    journal = journal_store.JournalStore(journal_path)
    try:
        journal.record_trade(_trade(snapshot, run_id=run_id))
    finally:
        journal.close()
    feature_store_dir = tmp_path / "features"
    feature_store = learning_feature_snapshots.LearningFeatureSnapshotStore(feature_store_dir)
    feature_store.record(snapshot)
    return journal_path, feature_store_dir


def test_execution_learning_sync_is_idempotent_and_preserves_execution_economics(
    tmp_path,
) -> None:
    snapshot = _snapshot()
    journal_path, feature_store_dir = _source(tmp_path, snapshot=snapshot)
    learning_root = tmp_path / "learning"

    first = execution_learning_sync_cli.execution_learning_sync_payload(
        journal_path=journal_path,
        feature_store_dir=feature_store_dir,
        learning_root=learning_root,
        candidate_id="candidate-paper-v1",
        kind=outcome_learning.LearningEvidenceKind.PAPER_EXECUTION,
        research_eligible_at_ms=30_000,
        expected_replay_run_id="run-1",
    )
    second = execution_learning_sync_cli.execution_learning_sync_payload(
        journal_path=journal_path,
        feature_store_dir=feature_store_dir,
        learning_root=learning_root,
        candidate_id="candidate-paper-v1",
        kind=outcome_learning.LearningEvidenceKind.PAPER_EXECUTION,
        research_eligible_at_ms=30_000,
        expected_replay_run_id="run-1",
    )

    assert first["scanned_trades"] == 1
    assert first["created_records"] == 1
    assert first["existing_records"] == 0
    assert second["created_records"] == 0
    assert second["existing_records"] == 1

    records = outcome_learning.LearningEvidenceLedger(learning_root).iter_records()
    assert len(records) == 1
    record = records[0]
    assert record.feature_snapshot_id == snapshot.snapshot_id
    assert record.gross_realized_pnl == Decimal("10")
    assert record.entry_fees == Decimal("0.45")
    assert record.exit_fees == Decimal("0.4545")
    assert record.net_pnl == Decimal("9.0955")
    assert record.net_r == Decimal("0.36382")


def test_execution_learning_sync_rejects_wrong_replay_run(tmp_path) -> None:
    snapshot = _snapshot()
    journal_path, feature_store_dir = _source(
        tmp_path,
        snapshot=snapshot,
        run_id="run-a",
    )

    with pytest.raises(ValueError, match="does not match expected replay run"):
        execution_learning_sync_cli.execution_learning_sync_payload(
            journal_path=journal_path,
            feature_store_dir=feature_store_dir,
            learning_root=tmp_path / "learning",
            candidate_id="candidate-paper-v1",
            kind=outcome_learning.LearningEvidenceKind.PAPER_EXECUTION,
            research_eligible_at_ms=30_000,
            expected_replay_run_id="run-b",
        )


def test_execution_learning_sync_rejects_missing_authenticated_snapshot(tmp_path) -> None:
    snapshot = _snapshot()
    journal_path, _feature_store_dir = _source(tmp_path, snapshot=snapshot)
    empty_store = tmp_path / "empty-features"

    with pytest.raises(ValueError, match="missing authenticated feature snapshot"):
        execution_learning_sync_cli.execution_learning_sync_payload(
            journal_path=journal_path,
            feature_store_dir=empty_store,
            learning_root=tmp_path / "learning",
            candidate_id="candidate-paper-v1",
            kind=outcome_learning.LearningEvidenceKind.PAPER_EXECUTION,
            research_eligible_at_ms=30_000,
            expected_replay_run_id="run-1",
        )


def test_execution_learning_sync_rejects_feature_after_trade_open(tmp_path) -> None:
    snapshot = _snapshot(as_of_ms=11_000)
    journal_path, feature_store_dir = _source(tmp_path, snapshot=snapshot)

    with pytest.raises(ValueError, match="after trade open"):
        execution_learning_sync_cli.execution_learning_sync_payload(
            journal_path=journal_path,
            feature_store_dir=feature_store_dir,
            learning_root=tmp_path / "learning",
            candidate_id="candidate-paper-v1",
            kind=outcome_learning.LearningEvidenceKind.PAPER_EXECUTION,
            research_eligible_at_ms=30_000,
            expected_replay_run_id="run-1",
        )
