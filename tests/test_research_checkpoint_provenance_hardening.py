from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from pytest import raises

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import (
    ResearchBatch,
    build_research_batch_seal,
    evaluate_research_checkpoint,
)
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.seals import seal_research_batch
from cocomelon.research.sequential import evaluate_checkpoint

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'


def _candidate(candidate_id: str = "provenance-r1") -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="provenance-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json=EXECUTION_CONFIG,
        risk_config_json=RISK_CONFIG,
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def _sample() -> TradeEvaluationSample:
    return TradeEvaluationSample(
        trade_id="provenance-trade-1",
        replay_run_id="provenance-replay-1",
        strategy_decision_id="strategy-decision-provenance-1",
        market=MarketId(dex="", coin="BTC"),
        direction=Direction.LONG,
        decision_timestamp_ms=DAY_MS + 10_000,
        opened_at_ms=DAY_MS + 11_000,
        closed_at_ms=DAY_MS + 16_000,
        score=Decimal("73"),
        lead_strategy="trend",
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=Decimal("1.02"),
        entry_fees=Decimal("0.01"),
        exit_fees=Decimal("0.01"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("1"),
        entry_slippage_amount=Decimal("0.003"),
        exit_slippage_amount=Decimal("0.004"),
        net_r=Decimal("0.1"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10001"),
        holding_duration_ms=5_000,
        reason_codes=("MAX_HOLD_EXPIRED",),
        schema_version=3,
    )


def _content_id(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_trade_observation_persists_canonical_sample_identity_and_provenance(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=3 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate())
    batch = ResearchBatch(
        batch_id="provenance-batch-1",
        source_id="provenance-source-1",
        replay_run_id="provenance-replay-1",
        interval=TimeInterval(DAY_MS, 2 * DAY_MS),
    )
    sample = _sample()

    evaluate_research_checkpoint(
        registry=registry,
        candidate_id="provenance-r1",
        batches=(batch,),
        batch_seals=(build_research_batch_seal(batch=batch, samples=(sample,)),),
        samples=(sample,),
    )

    row = registry.connection.execute(
        """
        SELECT payload_json
        FROM research_trade_observations
        WHERE candidate_id = ? AND trade_id = ?
        """,
        ("provenance-r1", sample.trade_id),
    ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_json"]))
    assert payload["sample_id"] == sample.sample_id
    assert payload["strategy_decision_id"] == sample.strategy_decision_id
    assert payload["evidence_class"] == sample.evidence_class.value
    assert payload["schema_version"] == sample.schema_version
    assert payload["lead_strategy"] == sample.lead_strategy
    assert payload["trend_regime"] == sample.trend_regime.value
    assert payload["volatility_regime"] == sample.volatility_regime.value
    assert payload["score"] == str(sample.score)
    assert payload["gross_realized_pnl"] == str(sample.gross_realized_pnl)
    registry.close()


def test_zero_trade_batches_remain_in_cumulative_report_provenance(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=4 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate())
    first_batch = ResearchBatch(
        batch_id="no-trade-batch-1",
        source_id="no-trade-source-1",
        replay_run_id="no-trade-replay-1",
        interval=TimeInterval(DAY_MS, 2 * DAY_MS),
    )
    second_batch = ResearchBatch(
        batch_id="no-trade-batch-2",
        source_id="no-trade-source-2",
        replay_run_id="no-trade-replay-2",
        interval=TimeInterval(2 * DAY_MS, 3 * DAY_MS),
    )

    first_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id="provenance-r1",
        batches=(first_batch,),
        batch_seals=(build_research_batch_seal(batch=first_batch, samples=()),),
        samples=(),
    )
    second_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id="provenance-r1",
        batches=(second_batch,),
        batch_seals=(build_research_batch_seal(batch=second_batch, samples=()),),
        samples=(),
    )

    assert first_report.batch_ids == ("no-trade-batch-1",)
    assert first_report.source_ids == ("no-trade-source-1",)
    assert second_report.batch_ids == ("no-trade-batch-1", "no-trade-batch-2")
    assert second_report.source_ids == ("no-trade-source-1", "no-trade-source-2")
    assert second_report.report_id != first_report.report_id
    registry.close()


def test_checkpoint_report_authenticates_admitted_batch_provenance(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=3 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate())
    batch = ResearchBatch(
        batch_id="auth-no-trade-batch",
        source_id="auth-no-trade-source",
        replay_run_id="auth-no-trade-replay",
        interval=TimeInterval(DAY_MS, 2 * DAY_MS),
    )
    registry.record_batch(
        candidate_id="provenance-r1",
        batch_id=batch.batch_id,
        source_id=batch.source_id,
        replay_run_id=batch.replay_run_id,
        interval=batch.interval,
    )
    seal = build_research_batch_seal(batch=batch, samples=())
    seal_research_batch(
        registry.connection,
        candidate_id="provenance-r1",
        batch_id=batch.batch_id,
        trade_ids=seal.trade_ids,
        sample_digest=seal.sample_digest,
    )
    checkpoint = evaluate_checkpoint(net_r_values=(), closed_trade_days=0)
    payload: dict[str, object] = {
        "candidate_id": "provenance-r1",
        "candidate_state": checkpoint.candidate_state.value,
        "checkpoint_state": checkpoint.checkpoint_state.value,
        "closed_trade_count": checkpoint.trade_count,
        "closed_trade_days": checkpoint.closed_trade_days,
        "posterior_probability_positive": None,
        "policy_digest": checkpoint.policy_digest,
        "reason_codes": list(checkpoint.reason_codes),
        "realized_closed_trade_max_drawdown_fraction": None,
        "max_realized_planned_risk_utilization": None,
        "batch_ids": [],
        "source_ids": [],
    }
    report_id = _content_id(payload)
    registry.record_performance_report(
        candidate_id="provenance-r1",
        report_id=report_id,
        payload=payload,
    )

    with raises(ResearchRegistryError, match="batch_ids|provenance"):
        registry.apply_checkpoint_state(
            "provenance-r1",
            ResearchCandidateState.RESEARCHING,
            report_id=report_id,
        )
    registry.close()
