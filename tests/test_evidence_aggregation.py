from __future__ import annotations

import hashlib
import importlib
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.cli_support import freeze_evaluation_dataset_payload
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore

SOL = MarketId("", "SOL")


def _aggregate_module() -> ModuleType:
    return importlib.import_module("cocomelon.evaluation.aggregate")


def _trade(*, suffix: str, run_id: str, opened_at_ms: int) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=SOL,
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
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=run_id,
    )


def _fact(item: TradeJournalEntry) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=item.strategy_decision_id,
        feature_snapshot_id=item.feature_snapshot_id,
        replay_run_id=item.replay_run_id or "",
        market=item.market,
        direction=item.direction,
        timestamp_ms=item.opened_at_ms - 100,
        score=Decimal("72"),
        lead_strategy="trend",
        signal_ids=(f"signal-{item.strategy_decision_id}",),
        reason_codes=("TREND_UP",),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def _source(
    root: Path,
    *,
    suffix: str,
    run_id: str,
    code_revision: str,
    start_ms: int,
) -> tuple[Path, Path, TradeJournalEntry, DecisionEvaluationFact]:
    root.mkdir(parents=True)
    journal_path = root / "journal.sqlite3"
    facts_path = root / "facts.sqlite3"
    item = _trade(suffix=suffix, run_id=run_id, opened_at_ms=start_ms + 1_000)
    item_fact = _fact(item)
    segment = SourceSegment(
        relative_path=f"events/{suffix}.jsonl",
        partition=f"events/2026-08-24/l2book/{suffix}",
        sha256=suffix[0] * 64,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=start_ms,
        last_available_at_ms=start_ms + 5_000,
    )
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=start_ms,
        end_ms=start_ms + 5_000,
        segments=(segment,),
        gap_refs=(),
        code_revision=code_revision,
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="native-taker-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )
    result = ReplayResult(
        manifest_id=manifest.manifest_id,
        run_id=run_id,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=manifest.start_ms,
        end_ms=manifest.end_ms,
        processed_events=10,
        processed_gaps=0,
        strategy_decisions=1,
        risk_approvals=1,
        risk_rejections=0,
        execution_attempts=2,
        fills=2,
        opened_positions=1,
        closed_positions=1,
        journal_observations=0,
        closed_trade_ids=(item.trade_id,),
        final_account_state_id=f"account-{run_id}",
        data_complete=True,
    )

    journal = JournalStore(journal_path)
    journal.record_trade(item)
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, run_id)
    journal.finish_run(result)
    journal.close()

    facts = EvaluationFactStore(facts_path)
    facts.record_decision_fact(item_fact)
    facts.close()
    return journal_path, facts_path, item, item_fact


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_aggregate_combines_fixed_revision_runs_without_mutating_sources(
    tmp_path: Path,
) -> None:
    aggregate = _aggregate_module()
    revision = "a" * 40
    first = _source(
        tmp_path / "source-a",
        suffix="a",
        run_id="run-a",
        code_revision=revision,
        start_ms=0,
    )
    second = _source(
        tmp_path / "source-b",
        suffix="b",
        run_id="run-b",
        code_revision=revision,
        start_ms=10_000,
    )
    source_paths = (first[0], first[1], second[0], second[1])
    before = tuple(_sha256(path) for path in source_paths)
    target_journal = tmp_path / "aggregate" / "journal.sqlite3"
    target_facts = tmp_path / "aggregate" / "facts.sqlite3"

    result = aggregate.aggregate_evaluation_evidence(
        target_journal,
        target_facts,
        (tmp_path / "source-a", tmp_path / "source-b"),
    )

    after = tuple(_sha256(path) for path in source_paths)
    assert after == before
    assert result.code_revision == revision
    assert result.run_ids == ("run-a", "run-b")
    assert result.trade_count == 2
    assert result.decision_fact_count == 2
    assert result.source_count == 2

    payload = freeze_evaluation_dataset_payload(
        target_journal,
        target_facts,
        result.run_ids,
    )
    assert payload["source_run_ids"] == ["run-a", "run-b"]
    assert payload["code_revision"] == revision
    assert payload["trade_count"] == 2
    assert payload["excluded_trade_count"] == 0


def test_aggregate_rejects_mixed_code_revisions_before_target_write(
    tmp_path: Path,
) -> None:
    aggregate = _aggregate_module()
    _source(
        tmp_path / "source-a",
        suffix="a",
        run_id="run-a",
        code_revision="a" * 40,
        start_ms=0,
    )
    _source(
        tmp_path / "source-b",
        suffix="b",
        run_id="run-b",
        code_revision="b" * 40,
        start_ms=10_000,
    )
    target_journal = tmp_path / "aggregate" / "journal.sqlite3"
    target_facts = tmp_path / "aggregate" / "facts.sqlite3"

    with pytest.raises(aggregate.EvidenceAggregationError, match="one code revision"):
        aggregate.aggregate_evaluation_evidence(
            target_journal,
            target_facts,
            (tmp_path / "source-a", tmp_path / "source-b"),
        )

    assert not target_journal.exists()
    assert not target_facts.exists()
