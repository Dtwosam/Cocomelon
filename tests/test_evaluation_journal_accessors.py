from decimal import Decimal
from pathlib import Path

from cocomelon.domain.journal import JournalObservation, ObservationKind, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore

MARKET = MarketId("", "SOL")


def observation(timestamp_ms: int, decision_id: str) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.STRATEGY_DECISION,
        timestamp_ms=timestamp_ms,
        market=MARKET,
        feature_snapshot_id=f"feature-{decision_id}",
        strategy_decision_id=decision_id,
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=("trend",),
        health_refs=(),
        replay_run_id="run-1",
    )


def trade(*, opened_at_ms: int, suffix: str) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 1_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-open-{suffix}",
        opening_attempt_id=f"attempt-open-{suffix}",
        exit_plan_ids=(f"plan-close-{suffix}",),
        exit_attempt_ids=(f"attempt-close-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-close-{suffix}"),
        position_action_ids=(f"action-close-{suffix}",),
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
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.36382"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10009.0955"),
        exit_reason="exit_thesis",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="run-1",
    )


def manifest() -> ReplayManifest:
    segment = SourceSegment(
        relative_path="events/a.jsonl",
        partition="events/2026-08-24/l2book/SOL",
        sha256="a" * 64,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=1_000,
        last_available_at_ms=4_000,
    )
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_000,
        end_ms=4_000,
        segments=(segment,),
        gap_refs=(),
        code_revision="abc123",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="native-taker-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def result(item: ReplayManifest) -> ReplayResult:
    return ReplayResult(
        manifest_id=item.manifest_id,
        run_id="run-1",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=item.start_ms,
        end_ms=item.end_ms,
        processed_events=4,
        processed_gaps=0,
        strategy_decisions=2,
        risk_approvals=2,
        risk_rejections=0,
        execution_attempts=4,
        fills=4,
        opened_positions=2,
        closed_positions=2,
        journal_observations=8,
        closed_trade_ids=("trade-placeholder",),
        final_account_state_id="account-final",
        data_complete=True,
    )


def test_journal_iterators_are_deterministic_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    later_trade = trade(opened_at_ms=3_000, suffix="b")
    earlier_trade = trade(opened_at_ms=1_000, suffix="a")
    later_observation = observation(3_000, "b")
    earlier_observation = observation(1_000, "a")
    store = JournalStore(path)
    store.record_trade(later_trade)
    store.record_trade(earlier_trade)
    store.record_observation(later_observation)
    store.record_observation(earlier_observation)
    store.close()

    reopened = JournalStore(path)
    assert tuple(reopened.iter_trades()) == (earlier_trade, later_trade)
    assert tuple(reopened.iter_observations()) == (earlier_observation, later_observation)
    reopened.close()


def test_replay_result_round_trips_and_iterates_from_journal_store(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    replay_manifest = manifest()
    replay_result = result(replay_manifest)
    store = JournalStore(path)
    store.record_manifest(replay_manifest)
    store.begin_run(replay_manifest.manifest_id, replay_result.run_id)
    store.finish_run(replay_result)
    store.close()

    reopened = JournalStore(path)
    assert reopened.load_replay_result(replay_result.run_id) == replay_result
    assert tuple(reopened.iter_replay_results()) == (replay_result,)
    reopened.close()
