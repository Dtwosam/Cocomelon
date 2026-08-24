from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import (
    CandidateDefinition,
    EdgeEvidenceStatus,
    EquityFactKind,
    EvaluationPolicy,
    FrozenCandidateSet,
    OOSStatus,
    SplitName,
    TimePartition,
)
from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    ReplayResult,
    SourceRecordKind,
    SourceSegment,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evaluation.dataset import build_evaluation_dataset
from cocomelon.evaluation.engine import EvaluationEngine, EvaluationRequest
from cocomelon.evaluation.facts import account_equity_fact, decision_evaluation_fact
from cocomelon.evaluation.sensitivity import predeclared_cost_stress_profiles
from cocomelon.evaluation.splits import freeze_split_manifest
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evaluation.walkforward import WalkForwardPlan
from cocomelon.execution.accounting import empty_account
from cocomelon.journal.observations import (
    observation_from_account_state,
    observation_from_strategy,
)
from cocomelon.journal.store import JournalStore
from cocomelon.replay.engine import ReplayEngine, ReplayPipeline

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
DATASET_END_MS = 80 * DAY_MS
TEST_START_MS = 40 * DAY_MS
MARKETS = (MarketId("", "BTC"), MarketId("", "ETH"), MarketId("", "SOL"))


@dataclass(slots=True)
class _EvaluationFixture:
    journal: JournalStore
    facts: EvaluationFactStore
    request: EvaluationRequest

    def close(self) -> None:
        self.facts.close()
        self.journal.close()


def _trade(
    index: int,
    *,
    market: MarketId,
    opened_at_ms: int,
    net_r: Decimal,
    replay_run_id: str | None,
    evidence_class: EvidenceClass = EvidenceClass.MICROSTRUCTURE,
    feature_snapshot_id: str | None = None,
    strategy_decision_id: str | None = None,
) -> TradeJournalEntry:
    initial_risk = Decimal("10")
    net_pnl = net_r * initial_risk
    entry = Decimal("100")
    exit_price = entry + net_pnl
    return TradeJournalEntry(
        market=market,
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 1_000,
        feature_snapshot_id=feature_snapshot_id or f"feature-{index}",
        strategy_decision_id=strategy_decision_id or f"strategy-{index}",
        risk_decision_id=f"risk-{index}",
        opening_plan_id=f"open-plan-{index}",
        opening_attempt_id=f"open-attempt-{index}",
        exit_plan_ids=(f"exit-plan-{index}",),
        exit_attempt_ids=(f"exit-attempt-{index}",),
        fill_ids=(f"open-fill-{index}", f"exit-fill-{index}"),
        position_action_ids=(f"position-action-{index}",),
        funding_event_ids=(),
        initial_stop=Decimal("95"),
        initial_risk_amount=initial_risk,
        entry_price=entry,
        exit_price=exit_price,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net_pnl,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net_pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=net_r,
        equity_before=Decimal("10000") + Decimal(index),
        equity_after=Decimal("10000") + Decimal(index) + net_pnl,
        exit_reason="synthetic_closed_outcome",
        health_refs=("synthetic-evaluation-only",),
        evidence_class=evidence_class,
        replay_run_id=replay_run_id,
    )


def _synthetic_feature(market: MarketId, *, opened_at_ms: int) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=opened_at_ms - 2_000,
        source_received_at_ms=opened_at_ms - 2_000,
        schema_version=1,
        day_return=None,
        funding=Decimal("0"),
        open_interest=Decimal("1"),
        day_notional_volume=Decimal("1"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("synthetic-evaluation-only",),
    )


def _source_manifest(*, row_count: int, evidence_class: EvidenceClass) -> ReplayManifest:
    return ReplayManifest(
        evidence_class=evidence_class,
        start_ms=0,
        end_ms=DATASET_END_MS,
        segments=(
            SourceSegment(
                relative_path="evaluation-fixture/closed-outcomes.jsonl",
                partition="synthetic-evaluation-only",
                sha256="a" * 64,
                byte_count=max(1, row_count),
                row_count=max(1, row_count),
                schema_version=1,
                first_available_at_ms=0,
                last_available_at_ms=DATASET_END_MS,
            ),
        ),
        gap_refs=(),
        code_revision="synthetic-evaluation-only",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="synthetic-evaluation-zero-cost",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def _profiles():
    wanted = {"base", "combined_stress"}
    return tuple(
        item
        for item in predeclared_cost_stress_profiles()
        if item.profile_id in wanted
    )


def _fixture(
    tmp_path: Path,
    *,
    trade_count: int,
    net_r: Decimal,
    concentrated: bool = False,
) -> _EvaluationFixture:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    replay_run_id = "synthetic-evaluation-run"
    trades_per_day = 3 if trade_count >= 100 else 1
    trades = []
    for index in range(trade_count):
        day = 40 + index // trades_per_day
        slot = index % trades_per_day
        opened_at_ms = day * DAY_MS + (8 + slot * 4) * HOUR_MS
        if concentrated:
            market = MARKETS[0] if index < trade_count // 2 else MARKETS[1 + index % 2]
        else:
            market = MARKETS[index % len(MARKETS)]
        feature = _synthetic_feature(market, opened_at_ms=opened_at_ms)
        decision = StrategyDecision(
            market=market,
            direction=Direction.LONG,
            score=Decimal("70"),
            timestamp_ms=opened_at_ms - 1_000,
            feature_snapshot_id=feature.snapshot_id,
            lead_strategy="trend",
            invalidation_price=Decimal("95"),
            signal_ids=(f"signal-{index}",),
            reason_codes=("SYNTHETIC_EVALUATION_ONLY",),
        )
        item = _trade(
            index,
            market=market,
            opened_at_ms=opened_at_ms,
            net_r=net_r,
            replay_run_id=replay_run_id,
            feature_snapshot_id=feature.snapshot_id,
            strategy_decision_id=decision.decision_id,
        )
        trades.append(item)
        journal.record_trade(item)
        facts.record_decision_fact(
            decision_evaluation_fact(
                decision,
                feature,
                replay_run_id=replay_run_id,
            )
        )

    manifest = _source_manifest(
        row_count=trade_count,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, replay_run_id)
    journal.finish_run(
        ReplayResult(
            manifest_id=manifest.manifest_id,
            run_id=replay_run_id,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            start_ms=0,
            end_ms=DATASET_END_MS,
            processed_events=max(1, trade_count),
            processed_gaps=0,
            strategy_decisions=trade_count,
            risk_approvals=trade_count,
            risk_rejections=0,
            execution_attempts=2 * trade_count,
            fills=2 * trade_count,
            opened_positions=trade_count,
            closed_positions=trade_count,
            journal_observations=trade_count,
            closed_trade_ids=tuple(item.trade_id for item in trades),
            final_account_state_id="synthetic-final-account",
            data_complete=True,
        )
    )
    dataset = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=(replay_run_id,),
        code_revision="synthetic-evaluation-only",
    ).manifest
    policy = EvaluationPolicy()
    split = freeze_split_manifest(
        dataset,
        train=TimePartition(SplitName.TRAIN, 0, 20 * DAY_MS),
        validation=TimePartition(SplitName.VALIDATION, 20 * DAY_MS, TEST_START_MS),
        test=TimePartition(SplitName.TEST, TEST_START_MS, DATASET_END_MS),
        policy=policy,
    )
    profiles = _profiles()
    candidates = FrozenCandidateSet(
        candidates=(
            CandidateDefinition(
                name="baseline",
                strategy_version="phase5-v1",
                risk_version="phase6-v1",
                execution_config_version="phase7-v1",
                code_revision="synthetic-evaluation-only",
                config_digest="c" * 64,
            ),
        ),
        sensitivity_profile_ids=tuple(item.profile_id for item in profiles),
        policy_id=policy.policy_id,
    )
    request = EvaluationRequest(
        dataset=dataset,
        split=split,
        candidates=candidates,
        policy=policy,
        walkforward_plan=WalkForwardPlan(
            dataset_manifest_id=dataset.manifest_id,
            first_window_start_ms=0,
            development_duration_ms=10 * DAY_MS,
            validation_duration_ms=10 * DAY_MS,
            evaluation_duration_ms=20 * DAY_MS,
            step_ms=10 * DAY_MS,
            embargo_ms=policy.split_embargo_ms,
            expanding=True,
            policy_id=policy.policy_id,
        ),
        sensitivity_profiles=profiles,
    )
    return _EvaluationFixture(journal=journal, facts=facts, request=request)


def test_positive_closed_outcome_fixture_reaches_candidate_edge(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, trade_count=120, net_r=Decimal("0.10"))
    try:
        result = EvaluationEngine(fixture.journal, fixture.facts).run(fixture.request)
        assert result.edge_status is EdgeEvidenceStatus.CANDIDATE_EDGE
        assert result.oos_status is OOSStatus.UNTOUCHED
        assert result.test_metrics.trade_count == 120
        assert result.test_metrics.covered_days == 40
        assert result.mean_net_r_confidence_interval is not None
        assert result.mean_net_r_confidence_interval.lower > 0
        assert sum(item.eligible for item in result.walkforward_results) >= 3
    finally:
        fixture.close()


def test_ready_weak_closed_outcome_fixture_reports_no_edge(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, trade_count=120, net_r=Decimal("-0.05"))
    try:
        result = EvaluationEngine(fixture.journal, fixture.facts).run(fixture.request)
        assert result.edge_status is EdgeEvidenceStatus.NO_EDGE_DEMONSTRATED
        assert result.oos_status is OOSStatus.UNTOUCHED
        assert result.test_metrics.trade_count == 120
    finally:
        fixture.close()


def test_small_closed_outcome_fixture_reports_insufficient_evidence(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, trade_count=40, net_r=Decimal("0.10"))
    try:
        result = EvaluationEngine(fixture.journal, fixture.facts).run(fixture.request)
        assert result.edge_status is EdgeEvidenceStatus.INSUFFICIENT_EVIDENCE
        assert result.test_metrics.trade_count == 40
        assert result.mean_net_r_confidence_interval is None
    finally:
        fixture.close()


def test_changed_candidate_contaminates_consumed_test(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, trade_count=120, net_r=Decimal("0.10"))
    try:
        first = EvaluationEngine(fixture.journal, fixture.facts).run(fixture.request)
        changed = FrozenCandidateSet(
            candidates=(
                CandidateDefinition(
                    name="changed-after-reveal",
                    strategy_version="phase5-v1",
                    risk_version="phase6-v1",
                    execution_config_version="phase7-v1",
                    code_revision="changed-after-reveal",
                    config_digest="d" * 64,
                ),
            ),
            sensitivity_profile_ids=fixture.request.candidates.sensitivity_profile_ids,
            policy_id=fixture.request.policy.policy_id,
        )
        second = EvaluationEngine(fixture.journal, fixture.facts).run(
            replace(fixture.request, candidates=changed)
        )

        assert first.oos_status is OOSStatus.UNTOUCHED
        assert second.oos_status is OOSStatus.CONTAMINATED
        assert second.edge_status is EdgeEvidenceStatus.OOS_CONTAMINATED
    finally:
        fixture.close()


def test_profitable_but_concentrated_candidate_is_not_edge(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        trade_count=120,
        net_r=Decimal("0.10"),
        concentrated=True,
    )
    try:
        result = EvaluationEngine(fixture.journal, fixture.facts).run(fixture.request)
        assert result.test_metrics.mean_net_r > 0
        assert result.test_metrics.max_market_positive_pnl_share is not None
        assert result.test_metrics.max_market_positive_pnl_share > Decimal("0.35")
        assert result.edge_status is EdgeEvidenceStatus.NO_EDGE_DEMONSTRATED
    finally:
        fixture.close()


class _SingleRecordSource:
    def __init__(self, record: ReplayRecord) -> None:
        self.record = record

    def iter_records(self, _manifest: ReplayManifest) -> Iterator[ReplayRecord]:
        yield self.record


def _integration_feature() -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MARKETS[2],
        as_of_ms=900,
        source_received_at_ms=900,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("100000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("phase8-phase9-integration",),
    )


def test_real_replay_lineage_joins_phase9_facts_without_digest_change(
    tmp_path: Path,
) -> None:
    feature = _integration_feature()
    decision = StrategyDecision(
        market=feature.market,
        direction=Direction.LONG,
        score=Decimal("70"),
        timestamp_ms=1_000,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("95"),
        signal_ids=("integration-signal",),
        reason_codes=("INTEGRATION_FIXTURE",),
    )
    account = empty_account(Decimal("10000"), 1_000)
    record = ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=1_000,
        source="phase8-phase9-integration",
        schema_version=1,
        market=feature.market.canonical,
        exchange_time_ms=900,
        event_key="integration-candle",
        payload_json=json.dumps({"close_px": "100"}),
        event_kind="candle",
    )
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        start_ms=1_000,
        end_ms=2_500,
        segments=(
            SourceSegment(
                relative_path="integration/candle.jsonl",
                partition="integration-candle",
                sha256="b" * 64,
                byte_count=1,
                row_count=1,
                schema_version=1,
                first_available_at_ms=1_000,
                last_available_at_ms=1_000,
            ),
        ),
        gap_refs=(),
        code_revision="phase8-phase9-integration",
        config_digest="e" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="integration-zero-cost",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )
    trade = _trade(
        999,
        market=feature.market,
        opened_at_ms=1_100,
        net_r=Decimal("0.10"),
        replay_run_id=None,
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        feature_snapshot_id=feature.snapshot_id,
        strategy_decision_id=decision.decision_id,
    )
    journal = JournalStore(tmp_path / "integration-journal.sqlite3")
    pipeline = ReplayPipeline(
        on_record=lambda _record, _now: (
            observation_from_strategy(decision, replay_run_id=None),
            observation_from_account_state(account, replay_run_id=None),
        ),
        finalize=lambda _end: (trade,),
    )
    replay_result = ReplayEngine(
        _SingleRecordSource(record),
        journal,
        pipeline,
    ).run(manifest)
    digest_before = replay_result.result_digest

    facts = EvaluationFactStore(tmp_path / "integration-facts.sqlite3")
    decision_fact = decision_evaluation_fact(
        decision,
        feature,
        replay_run_id=replay_result.run_id,
    )
    equity_fact = account_equity_fact(
        account,
        replay_run_id=replay_result.run_id,
        kind=EquityFactKind.ACCOUNT_UPDATE,
    )
    facts.record_decision_fact(decision_fact)
    facts.record_equity_fact(equity_fact)
    built = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=(replay_result.run_id,),
        code_revision="phase9-integration",
    )

    assert replay_result.result_digest == digest_before
    assert built.manifest.trade_ids == replay_result.closed_trade_ids
    assert built.manifest.decision_fact_ids == (decision_fact.fact_id,)
    assert built.manifest.equity_fact_ids == (equity_fact.fact_id,)
    assert len(built.samples) == 1
    assert built.samples[0].trade_id == replay_result.closed_trade_ids[0]
    facts.close()
    journal.close()
