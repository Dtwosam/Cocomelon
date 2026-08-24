from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation import mainnet_aggregate, mainnet_cli
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore

SOL = MarketId("", "SOL")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _source(
    root: Path,
    *,
    run_id: str = "run-a",
    code_revision: str = "a" * 40,
    data_complete: bool = True,
    gap_count: int = 0,
    evidence_kind: str = "genuine_public_hyperliquid_mainnet",
    record_live_orders: bool = False,
    replay_live_orders: bool = False,
) -> None:
    root.mkdir(parents=True)
    journal_path = root / "journal.sqlite3"
    facts_path = root / "facts.sqlite3"
    trade = TradeJournalEntry(
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
    fact = DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=run_id,
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
    segment = SourceSegment(
        relative_path="events/a.jsonl",
        partition="events/2026-08-24/l2_book/SOL",
        sha256="a" * 64,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=0,
        last_available_at_ms=5_000,
    )
    gap_refs = () if data_complete else ("gap:l2Book:SOL:100:200:recovered",)
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=5_000,
        segments=(segment,),
        gap_refs=gap_refs,
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
        start_ms=0,
        end_ms=5_000,
        processed_events=10,
        processed_gaps=gap_count,
        strategy_decisions=1,
        risk_approvals=1,
        risk_rejections=0,
        execution_attempts=2,
        fills=2,
        opened_positions=1,
        closed_positions=1,
        journal_observations=0,
        closed_trade_ids=(trade.trade_id,),
        final_account_state_id="account-a",
        data_complete=data_complete,
    )
    journal = JournalStore(journal_path)
    journal.record_trade(trade)
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, run_id)
    journal.finish_run(result)
    journal.close()
    facts = EvaluationFactStore(facts_path)
    facts.record_decision_fact(fact)
    facts.close()

    session_id = f"session-{run_id}"
    _write_json(
        root / "cohort-summary.json",
        {
            "checked_out_code_revision": code_revision,
            "closed_trade_count": 1,
            "data_complete": data_complete,
            "dataset_trade_count": 1,
            "economic_claim": "none",
            "evidence_kind": evidence_kind,
            "recorded_duplicate_count": 0,
            "recorded_gap_count": gap_count,
            "recording_session_id": session_id,
            "replay_run_id": run_id,
        },
    )
    _write_json(
        root / "record.json",
        {
            "anomaly_count": 0,
            "duplicate_count": 0,
            "gap_count": gap_count,
            "live_orders": record_live_orders,
            "network_access": True,
            "session_id": session_id,
        },
    )
    _write_json(
        root / "replay.json",
        {
            "closed_trade_ids": [trade.trade_id],
            "data_complete": data_complete,
            "live_orders": replay_live_orders,
            "network_access": False,
            "run_id": run_id,
        },
    )


def test_genuine_mainnet_aggregation_accepts_attested_complete_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source(source)
    target = tmp_path / "aggregate"

    result = mainnet_aggregate.aggregate_genuine_mainnet_evidence(
        target / "journal.sqlite3",
        target / "facts.sqlite3",
        (source,),
    )

    assert result.code_revision == "a" * 40
    assert result.run_ids == ("run-a",)
    assert result.trade_count == 1
    corpus = json.loads((target / "genuine-mainnet-corpus.json").read_text(encoding="utf-8"))
    assert corpus["run_ids"] == ["run-a"]
    assert corpus["evidence_kind"] == "genuine_public_hyperliquid_mainnet"
    validated = mainnet_aggregate.validate_genuine_mainnet_corpus(
        target / "journal.sqlite3",
        target / "facts.sqlite3",
    )
    assert validated == result


def test_genuine_mainnet_aggregation_rejects_incomplete_source_before_write(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _source(source, data_complete=False, gap_count=2)
    target = tmp_path / "aggregate"

    with pytest.raises(mainnet_aggregate.EvidenceAggregationError, match="complete"):
        mainnet_aggregate.aggregate_genuine_mainnet_evidence(
            target / "journal.sqlite3",
            target / "facts.sqlite3",
            (source,),
        )

    assert not target.exists()


def test_genuine_mainnet_aggregation_rejects_wrong_kind_and_live_semantics(
    tmp_path: Path,
) -> None:
    wrong_kind = tmp_path / "wrong-kind"
    _source(wrong_kind, evidence_kind="synthetic_fixture")
    live = tmp_path / "live"
    _source(live, run_id="run-live", record_live_orders=True)

    with pytest.raises(mainnet_aggregate.EvidenceAggregationError, match="genuine public"):
        mainnet_aggregate.aggregate_genuine_mainnet_evidence(
            tmp_path / "target-a" / "journal.sqlite3",
            tmp_path / "target-a" / "facts.sqlite3",
            (wrong_kind,),
        )
    with pytest.raises(mainnet_aggregate.EvidenceAggregationError, match="paper-only"):
        mainnet_aggregate.aggregate_genuine_mainnet_evidence(
            tmp_path / "target-b" / "journal.sqlite3",
            tmp_path / "target-b" / "facts.sqlite3",
            (live,),
        )


def test_genuine_mainnet_aggregation_rejects_attestation_store_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source(source)
    summary_path = source / "cohort-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["replay_run_id"] = "different-run"
    _write_json(summary_path, summary)

    with pytest.raises(mainnet_aggregate.EvidenceAggregationError, match="run id"):
        mainnet_aggregate.aggregate_genuine_mainnet_evidence(
            tmp_path / "target" / "journal.sqlite3",
            tmp_path / "target" / "facts.sqlite3",
            (source,),
        )


def test_genuine_mainnet_corpus_accumulates_only_attested_runs(tmp_path: Path) -> None:
    revision = "a" * 40
    first = tmp_path / "first"
    second = tmp_path / "second"
    _source(first, run_id="run-a", code_revision=revision)
    _source(second, run_id="run-b", code_revision=revision)
    target = tmp_path / "aggregate"

    mainnet_aggregate.aggregate_genuine_mainnet_evidence(
        target / "journal.sqlite3",
        target / "facts.sqlite3",
        (first,),
    )
    result = mainnet_aggregate.aggregate_genuine_mainnet_evidence(
        target / "journal.sqlite3",
        target / "facts.sqlite3",
        (second,),
    )

    assert result.run_ids == ("run-a", "run-b")
    corpus = json.loads((target / "genuine-mainnet-corpus.json").read_text(encoding="utf-8"))
    assert corpus["run_ids"] == ["run-a", "run-b"]
    assert [item["run_id"] for item in corpus["source_attestations"]] == ["run-a", "run-b"]


def test_genuine_mainnet_aggregation_cli_requires_local_attested_sources() -> None:
    parser = mainnet_cli.build_parser()
    args = parser.parse_args(
        [
            "aggregate",
            "--journal",
            "aggregate/journal.sqlite3",
            "--facts",
            "aggregate/facts.sqlite3",
            "--source-root",
            "artifact/output",
        ]
    )
    assert args.command == "aggregate"
    assert args.source_root == [Path("artifact/output")]
