from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.dataset import EvaluationDatasetError, build_evaluation_dataset
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore

SOL = MarketId("", "SOL")
ETH = MarketId("", "ETH")


def trade(
    *,
    suffix: str,
    run_id: str,
    market: MarketId = SOL,
    evidence_class: EvidenceClass = EvidenceClass.MICROSTRUCTURE,
    opened_at_ms: int = 1_000,
) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=market,
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
        evidence_class=evidence_class,
        replay_run_id=run_id,
    )


def fact(
    item: TradeJournalEntry,
    *,
    market: MarketId | None = None,
    direction: Direction | None = None,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=item.strategy_decision_id,
        feature_snapshot_id=item.feature_snapshot_id,
        replay_run_id=item.replay_run_id or "",
        market=item.market if market is None else market,
        direction=item.direction if direction is None else direction,
        timestamp_ms=item.opened_at_ms - 100,
        score=Decimal("72"),
        lead_strategy="trend",
        signal_ids=(f"signal-{item.strategy_decision_id}",),
        reason_codes=("TREND_UP",),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def replay_manifest(
    *,
    suffix: str,
    evidence_class: EvidenceClass,
    start_ms: int,
    end_ms: int,
) -> ReplayManifest:
    event_kind = "l2book" if evidence_class is EvidenceClass.MICROSTRUCTURE else "candle"
    segment = SourceSegment(
        relative_path=f"events/{suffix}.jsonl",
        partition=f"events/2026-08-24/{event_kind}/SOL",
        sha256=("a" if suffix == "a" else "b") * 64,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=start_ms,
        last_available_at_ms=end_ms,
    )
    return ReplayManifest(
        evidence_class=evidence_class,
        start_ms=start_ms,
        end_ms=end_ms,
        segments=(segment,),
        gap_refs=(),
        code_revision="phase8-source",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version=(
            "phase7-v1" if evidence_class is EvidenceClass.MICROSTRUCTURE else None
        ),
        fee_schedule_id=(
            "native-taker-v1" if evidence_class is EvidenceClass.MICROSTRUCTURE else None
        ),
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def replay_result(
    manifest: ReplayManifest,
    *,
    run_id: str,
    trade_ids: tuple[str, ...],
    data_complete: bool = True,
) -> ReplayResult:
    return ReplayResult(
        manifest_id=manifest.manifest_id,
        run_id=run_id,
        evidence_class=manifest.evidence_class,
        start_ms=manifest.start_ms,
        end_ms=manifest.end_ms,
        processed_events=10,
        processed_gaps=0 if data_complete else 1,
        strategy_decisions=len(trade_ids),
        risk_approvals=len(trade_ids),
        risk_rejections=0,
        execution_attempts=2 * len(trade_ids),
        fills=2 * len(trade_ids),
        opened_positions=len(trade_ids),
        closed_positions=len(trade_ids),
        journal_observations=4 * len(trade_ids),
        closed_trade_ids=trade_ids,
        final_account_state_id=f"account-{run_id}",
        data_complete=data_complete,
    )


def persist_run(
    journal: JournalStore,
    *,
    run_id: str,
    manifest: ReplayManifest,
    trades: tuple[TradeJournalEntry, ...],
    data_complete: bool = True,
) -> ReplayResult:
    for item in trades:
        journal.record_trade(item)
    result = replay_result(
        manifest,
        run_id=run_id,
        trade_ids=tuple(item.trade_id for item in trades),
        data_complete=data_complete,
    )
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, run_id)
    journal.finish_run(result)
    return result


def stores(tmp_path: Path) -> tuple[JournalStore, EvaluationFactStore]:
    return (
        JournalStore(tmp_path / "journal.sqlite3"),
        EvaluationFactStore(tmp_path / "evaluation.sqlite3"),
    )


def test_exact_join_builds_sample_and_persists_manifest(tmp_path: Path) -> None:
    journal, facts = stores(tmp_path)
    item = trade(suffix="a", run_id="run-a")
    source_manifest = replay_manifest(
        suffix="a",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
    )
    source_result = persist_run(
        journal,
        run_id="run-a",
        manifest=source_manifest,
        trades=(item,),
    )
    item_fact = fact(item)
    facts.record_decision_fact(item_fact)

    built = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-a",),
        code_revision="phase9-test",
    )

    assert len(built.samples) == 1
    sample = built.samples[0]
    assert sample.trade_id == item.trade_id
    assert sample.strategy_decision_id == item.strategy_decision_id
    assert sample.market == item.market
    assert sample.direction is item.direction
    assert sample.score == Decimal("72")
    assert sample.lead_strategy == "trend"
    assert sample.trend_regime is TrendRegime.UP
    assert sample.volatility_regime is VolatilityRegime.NORMAL
    assert built.excluded_trade_ids == ()
    assert built.manifest.sources[0].manifest_id == source_manifest.manifest_id
    assert built.manifest.sources[0].result_digest == source_result.result_digest
    assert facts.load_dataset_manifest(built.manifest.manifest_id) == built.manifest
    journal.close()
    facts.close()


def test_missing_decision_fact_is_excluded_with_reason(tmp_path: Path) -> None:
    journal, facts = stores(tmp_path)
    item = trade(suffix="a", run_id="run-a")
    manifest = replay_manifest(
        suffix="a",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
    )
    persist_run(journal, run_id="run-a", manifest=manifest, trades=(item,))

    built = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-a",),
        code_revision="phase9-test",
    )

    assert built.samples == ()
    assert built.excluded_trade_ids == (item.trade_id,)
    assert built.exclusion_reasons == ((item.trade_id, "MISSING_DECISION_FACT"),)
    journal.close()
    facts.close()


@pytest.mark.parametrize(
    ("fact_market", "fact_direction", "reason"),
    [
        (ETH, Direction.LONG, "DECISION_MARKET_MISMATCH"),
        (SOL, Direction.SHORT, "DECISION_DIRECTION_MISMATCH"),
    ],
)
def test_mismatched_decision_fact_is_excluded(
    tmp_path: Path,
    fact_market: MarketId,
    fact_direction: Direction,
    reason: str,
) -> None:
    journal, facts = stores(tmp_path)
    item = trade(suffix="a", run_id="run-a")
    manifest = replay_manifest(
        suffix="a",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
    )
    persist_run(journal, run_id="run-a", manifest=manifest, trades=(item,))
    facts.record_decision_fact(fact(item, market=fact_market, direction=fact_direction))

    built = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-a",),
        code_revision="phase9-test",
    )

    assert built.samples == ()
    assert built.exclusion_reasons == ((item.trade_id, reason),)
    journal.close()
    facts.close()


def test_unknown_replay_result_fails_closed(tmp_path: Path) -> None:
    journal, facts = stores(tmp_path)

    with pytest.raises(EvaluationDatasetError, match="UNKNOWN_REPLAY_RESULT"):
        build_evaluation_dataset(
            journal,
            facts,
            replay_run_ids=("missing-run",),
            code_revision="phase9-test",
        )
    journal.close()
    facts.close()


def test_mixed_evidence_rejects_by_default_and_diagnostic_mode_is_non_primary(
    tmp_path: Path,
) -> None:
    journal, facts = stores(tmp_path)
    micro = trade(suffix="a", run_id="run-a", evidence_class=EvidenceClass.MICROSTRUCTURE)
    candle = trade(
        suffix="b",
        run_id="run-b",
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        opened_at_ms=6_000,
    )
    micro_manifest = replay_manifest(
        suffix="a",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
    )
    candle_manifest = replay_manifest(
        suffix="b",
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        start_ms=5_000,
        end_ms=10_000,
    )
    persist_run(journal, run_id="run-a", manifest=micro_manifest, trades=(micro,))
    persist_run(journal, run_id="run-b", manifest=candle_manifest, trades=(candle,))
    facts.record_decision_fact(fact(micro))
    facts.record_decision_fact(fact(candle))

    with pytest.raises(EvaluationDatasetError, match="MIXED_EVIDENCE"):
        build_evaluation_dataset(
            journal,
            facts,
            replay_run_ids=("run-a", "run-b"),
            code_revision="phase9-test",
        )

    diagnostic = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-b", "run-a"),
        code_revision="phase9-test",
        allow_mixed_evidence=True,
    )
    assert diagnostic.manifest.mixed_evidence_diagnostic is True
    assert diagnostic.manifest.evidence_class is None
    assert len(diagnostic.samples) == 2
    journal.close()
    facts.close()


def test_incomplete_source_marks_dataset_incomplete(tmp_path: Path) -> None:
    journal, facts = stores(tmp_path)
    item = trade(suffix="a", run_id="run-a")
    manifest = replay_manifest(
        suffix="a",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
    )
    persist_run(
        journal,
        run_id="run-a",
        manifest=manifest,
        trades=(item,),
        data_complete=False,
    )
    facts.record_decision_fact(fact(item))

    built = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-a",),
        code_revision="phase9-test",
    )

    assert built.manifest.data_complete is False
    assert built.manifest.sources[0].data_complete is False
    journal.close()
    facts.close()


def test_run_enumeration_does_not_change_dataset_identity(tmp_path: Path) -> None:
    journal, facts = stores(tmp_path)
    first = trade(suffix="a", run_id="run-a")
    second = trade(suffix="b", run_id="run-b", opened_at_ms=6_000)
    first_manifest = replay_manifest(
        suffix="a",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
    )
    second_manifest = replay_manifest(
        suffix="b",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=5_000,
        end_ms=10_000,
    )
    persist_run(journal, run_id="run-b", manifest=second_manifest, trades=(second,))
    persist_run(journal, run_id="run-a", manifest=first_manifest, trades=(first,))
    facts.record_decision_fact(fact(second))
    facts.record_decision_fact(fact(first))

    forward = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-a", "run-b"),
        code_revision="phase9-test",
    )
    reverse = build_evaluation_dataset(
        journal,
        facts,
        replay_run_ids=("run-b", "run-a"),
        code_revision="phase9-test",
    )

    assert forward.manifest.manifest_id == reverse.manifest.manifest_id
    assert forward.samples == reverse.samples
    assert forward.exclusion_reasons == reverse.exclusion_reasons
    journal.close()
    facts.close()
