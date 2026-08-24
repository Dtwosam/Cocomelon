from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import (
    CandidateDefinition,
    DecisionEvaluationFact,
    EvaluationPolicy,
    FrozenCandidateSet,
    OOSStatus,
    SplitName,
    TimePartition,
)
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.dataset import build_evaluation_dataset
from cocomelon.evaluation.engine import EvaluationEngine, EvaluationRequest
from cocomelon.evaluation.sensitivity import predeclared_cost_stress_profiles
from cocomelon.evaluation.splits import freeze_split_manifest
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evaluation.walkforward import WalkForwardPlan
from cocomelon.journal.store import JournalStore

SOL = MarketId("", "SOL")


def _trade() -> TradeJournalEntry:
    return TradeJournalEntry(
        market=SOL,
        direction=Direction.LONG,
        opened_at_ms=70_000,
        closed_at_ms=70_001,
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
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("1"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("1"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=1,
        mfe=None,
        mae=None,
        net_r=Decimal("0.1"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10001"),
        exit_reason="exit_thesis",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="run-a",
    )


def _source_manifest() -> ReplayManifest:
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=100_000,
        segments=(
            SourceSegment(
                relative_path="events/a.jsonl",
                partition="events/2026-08-24/l2book/SOL",
                sha256="a" * 64,
                byte_count=100,
                row_count=2,
                schema_version=1,
                first_available_at_ms=0,
                last_available_at_ms=100_000,
            ),
        ),
        gap_refs=(),
        code_revision="phase8-source",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="native-taker-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def _persist_phase8(journal: JournalStore) -> TradeJournalEntry:
    item = _trade()
    manifest = _source_manifest()
    journal.record_trade(item)
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, "run-a")
    journal.finish_run(
        ReplayResult(
            manifest_id=manifest.manifest_id,
            run_id="run-a",
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            start_ms=0,
            end_ms=100_000,
            processed_events=10,
            processed_gaps=0,
            strategy_decisions=1,
            risk_approvals=1,
            risk_rejections=0,
            execution_attempts=2,
            fills=2,
            opened_positions=1,
            closed_positions=1,
            journal_observations=4,
            closed_trade_ids=(item.trade_id,),
            final_account_state_id="account-final",
            data_complete=True,
        )
    )
    return item


def _record_decision(facts: EvaluationFactStore, item: TradeJournalEntry) -> None:
    facts.record_decision_fact(
        DecisionEvaluationFact(
            strategy_decision_id=item.strategy_decision_id,
            feature_snapshot_id=item.feature_snapshot_id,
            replay_run_id="run-a",
            market=item.market,
            direction=item.direction,
            timestamp_ms=69_900,
            score=Decimal("70"),
            lead_strategy="trend",
            signal_ids=("signal-a",),
            reason_codes=("TREND_UP",),
            trend_regime=TrendRegime.UP,
            volatility_regime=VolatilityRegime.NORMAL,
        )
    )


def _policy() -> EvaluationPolicy:
    return EvaluationPolicy(
        min_oos_trades=1,
        min_oos_days=1,
        min_walkforward_windows=1,
        min_trades_per_walkforward_window=1,
        min_score_bucket_trades=1,
        bootstrap_block_days=1,
        bootstrap_resamples=20,
        split_embargo_ms=0,
    )


def _request(
    journal: JournalStore,
    facts: EvaluationFactStore,
) -> EvaluationRequest:
    rules = _policy()
    dataset = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-a",),
        code_revision="phase9-test",
    ).manifest
    split = freeze_split_manifest(
        dataset,
        train=TimePartition(SplitName.TRAIN, 0, 30_000),
        validation=TimePartition(SplitName.VALIDATION, 30_000, 60_000),
        test=TimePartition(SplitName.TEST, 60_000, 100_000),
        policy=rules,
    )
    profiles = predeclared_cost_stress_profiles()
    selected = tuple(item for item in profiles if item.profile_id in {"base", "combined_stress"})
    candidates = FrozenCandidateSet(
        candidates=(
            CandidateDefinition(
                name="baseline",
                strategy_version="phase5-v1",
                risk_version="phase6-v1",
                execution_config_version="phase7-v1",
                code_revision="phase9-test",
                config_digest="c" * 64,
            ),
        ),
        sensitivity_profile_ids=tuple(item.profile_id for item in selected),
        policy_id=rules.policy_id,
    )
    return EvaluationRequest(
        dataset=dataset,
        split=split,
        candidates=candidates,
        policy=rules,
        walkforward_plan=WalkForwardPlan(
            dataset_manifest_id=dataset.manifest_id,
            first_window_start_ms=0,
            development_duration_ms=30_000,
            validation_duration_ms=30_000,
            evaluation_duration_ms=40_000,
            step_ms=40_000,
            embargo_ms=0,
            expanding=True,
            policy_id=rules.policy_id,
        ),
        sensitivity_profiles=selected,
    )


def test_identical_engine_rerun_reuses_exact_result_after_restart(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.sqlite3"
    facts_path = tmp_path / "evaluation.sqlite3"
    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    item = _persist_phase8(journal)
    _record_decision(facts, item)
    request = _request(journal, facts)

    first = EvaluationEngine(journal, facts).run(request)
    assert first.oos_status is OOSStatus.UNTOUCHED
    assert facts.load_evaluation_result(first.evaluation_id) == first
    journal.close()
    facts.close()

    reopened_journal = JournalStore(journal_path)
    reopened_facts = EvaluationFactStore(facts_path)
    second = EvaluationEngine(reopened_journal, reopened_facts).run(request)

    assert second == first
    assert second.evaluation_id == first.evaluation_id
    assert second.result_digest == first.result_digest
    assert reopened_facts.load_evaluation_result(first.evaluation_id) == first
    consumption_count = reopened_facts.connection.execute(
        "SELECT COUNT(*) FROM evaluation_oos_consumptions"
    ).fetchone()
    result_count = reopened_facts.connection.execute(
        "SELECT COUNT(*) FROM evaluation_results"
    ).fetchone()
    consumed_by = reopened_facts.connection.execute(
        "SELECT consumed_by_evaluation_id FROM evaluation_oos_consumptions"
    ).fetchone()
    assert consumption_count == (1,)
    assert result_count == (1,)
    assert consumed_by == (first.evaluation_id,)
    reopened_journal.close()
    reopened_facts.close()
