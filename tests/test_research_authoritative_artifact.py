from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from cocomelon.research.artifact import verify_research_batch_artifact

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import JournalObservation, ObservationKind, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore

SOL = MarketId("", "SOL")


def _trade(run_id: str) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=SOL,
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        feature_snapshot_id="feature-a",
        strategy_decision_id="strategy-a",
        risk_decision_id="risk-a",
        opening_plan_id="plan-open-a",
        opening_attempt_id="attempt-open-a",
        exit_plan_ids=("plan-close-a",),
        exit_attempt_ids=("attempt-close-a",),
        fill_ids=("fill-open-a", "fill-close-a"),
        position_action_ids=("action-close-a",),
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
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.36382"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10009.0955"),
        exit_reason="exit_thesis",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=run_id,
    )


def _fact(trade: TradeJournalEntry) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=trade.replay_run_id or "",
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=900,
        score=Decimal("72"),
        lead_strategy="trend",
        signal_ids=("signal-a",),
        reason_codes=("TREND_UP",),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def _manifest() -> ReplayManifest:
    segment = SourceSegment(
        relative_path="events/a.jsonl",
        partition="events/2026-08-31/l2book/SOL",
        sha256="a" * 64,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=0,
        last_available_at_ms=5_000,
    )
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
        segments=(segment,),
        gap_refs=(),
        code_revision="1" * 40,
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="native-taker-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def _write_artifact(
    root: Path,
    *,
    hard_risk: bool = False,
    live_orders: bool = False,
) -> TradeJournalEntry:
    root.mkdir(parents=True, exist_ok=True)
    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    run_id = "research-run-a"
    trade = _trade(run_id)
    manifest = _manifest()
    journal.record_trade(trade)
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, run_id)
    result = ReplayResult(
        manifest_id=manifest.manifest_id,
        run_id=run_id,
        evidence_class=manifest.evidence_class,
        start_ms=manifest.start_ms,
        end_ms=manifest.end_ms,
        processed_events=10,
        processed_gaps=0,
        strategy_decisions=1,
        risk_approvals=1,
        risk_rejections=1 if hard_risk else 0,
        execution_attempts=2,
        fills=2,
        opened_positions=1,
        closed_positions=1,
        journal_observations=5,
        closed_trade_ids=(trade.trade_id,),
        final_account_state_id="account-final",
        data_complete=True,
    )
    journal.finish_run(result)
    if hard_risk:
        journal.record_observation(
            JournalObservation(
                kind=ObservationKind.RISK_DECISION,
                timestamp_ms=2_500,
                market=SOL,
                feature_snapshot_id=None,
                strategy_decision_id="strategy-lockout",
                risk_decision_id="risk-lockout",
                plan_id=None,
                attempt_id=None,
                position_action_id=None,
                account_state_id=None,
                reason_codes=("daily_loss_lockout",),
                health_refs=("paper-state-healthy",),
                replay_run_id=run_id,
            )
        )
    facts.record_decision_fact(_fact(trade))
    journal.close()
    facts.close()
    (root / "replay.json").write_text(
        json.dumps(
            {
                "data_complete": True,
                "live_orders": live_orders,
                "manifest_id": manifest.manifest_id,
                "network_access": False,
                "result_digest": result.result_digest,
                "run_id": run_id,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return trade


def test_verified_batch_derives_complete_seal_and_planned_risk_from_artifact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifact"
    trade = _write_artifact(root)

    verified = verify_research_batch_artifact(
        root,
        batch_id="batch-a",
        source_id="source-a",
    )

    assert verified.replay_run_id == "research-run-a"
    assert verified.interval.start_ms == 0
    assert verified.interval.end_ms == 5_000
    assert verified.trade_ids == (trade.trade_id,)
    assert tuple(sample.trade_id for sample in verified.samples) == (trade.trade_id,)
    assert verified.operational_failure is False
    assert verified.hard_risk_failure is False
    assert verified.planned_risk_fractions == ((trade.trade_id, Decimal("0.0025")),)
    assert len(verified.source_digest) == 64
    assert len(verified.sample_digest) == 64


def test_verified_batch_derives_hard_risk_from_journal_not_caller_input(tmp_path: Path) -> None:
    root = tmp_path / "artifact"
    _write_artifact(root, hard_risk=True)

    verified = verify_research_batch_artifact(
        root,
        batch_id="batch-a",
        source_id="source-a",
    )

    assert verified.hard_risk_failure is True
    assert "daily_loss_lockout" in verified.health_reason_codes


def test_verified_batch_treats_live_order_replay_as_operational_failure(tmp_path: Path) -> None:
    root = tmp_path / "artifact"
    _write_artifact(root, live_orders=True)

    verified = verify_research_batch_artifact(
        root,
        batch_id="batch-a",
        source_id="source-a",
    )

    assert verified.operational_failure is True
    assert "unexpected_live_orders" in verified.health_reason_codes
