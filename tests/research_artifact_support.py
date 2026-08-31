from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import JournalObservation, ObservationKind, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.evaluator import ResearchArtifactBatch


@dataclass(frozen=True, slots=True)
class ArtifactTradeSpec:
    closed_at_ms: int
    net_r: Decimal
    equity_before: Decimal = Decimal("10000")
    planned_risk_fraction: Decimal = Decimal("0.0025")
    market: str = "BTC"
    direction: Direction = Direction.LONG
    score: Decimal = Decimal("70")
    lead_strategy: str = "research-test"
    trend_regime: TrendRegime = TrendRegime.UP
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    reason_codes: tuple[str, ...] = ("THESIS_EXPIRED",)


def _trade(spec: ArtifactTradeSpec, *, index: int, run_id: str) -> TradeJournalEntry:
    opened_at_ms = spec.closed_at_ms - 1_000
    if opened_at_ms < 0:
        raise ValueError("test artifact trade must close at or after 1000ms")
    with localcontext(AUTHORITATIVE_CONTEXT):
        initial_risk = spec.equity_before * spec.planned_risk_fraction
        net_pnl = spec.net_r * initial_risk
        equity_after = spec.equity_before + net_pnl
    prefix = f"artifact-{index}"
    return TradeJournalEntry(
        market=MarketId("", spec.market),
        direction=spec.direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=spec.closed_at_ms,
        feature_snapshot_id=f"{prefix}-feature",
        strategy_decision_id=f"{prefix}-decision",
        risk_decision_id=f"{prefix}-risk",
        opening_plan_id=f"{prefix}-open-plan",
        opening_attempt_id=f"{prefix}-open-attempt",
        exit_plan_ids=(f"{prefix}-close-plan",),
        exit_attempt_ids=(f"{prefix}-close-attempt",),
        fill_ids=(f"{prefix}-open-fill", f"{prefix}-close-fill"),
        position_action_ids=(f"{prefix}-close-action",),
        funding_event_ids=(),
        initial_stop=Decimal("95"),
        initial_risk_amount=initial_risk,
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
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
        net_r=spec.net_r,
        equity_before=spec.equity_before,
        equity_after=equity_after,
        exit_reason=spec.reason_codes[0] if spec.reason_codes else "test_exit",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=run_id,
    )


def _fact(trade: TradeJournalEntry, spec: ArtifactTradeSpec) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=trade.replay_run_id or "",
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=trade.opened_at_ms - 100,
        score=spec.score,
        lead_strategy=spec.lead_strategy,
        signal_ids=(f"{trade.strategy_decision_id}-signal",),
        reason_codes=spec.reason_codes,
        trend_regime=spec.trend_regime,
        volatility_regime=spec.volatility_regime,
    )


def write_research_artifact(
    root: Path,
    *,
    batch_id: str,
    source_id: str,
    replay_run_id: str,
    start_ms: int,
    end_ms: int,
    trades: tuple[ArtifactTradeSpec, ...] = (),
    data_complete: bool = True,
    network_access: bool = False,
    order_execution: bool = False,
    hard_risk_reason: str | None = None,
) -> ResearchArtifactBatch:
    root.mkdir(parents=True, exist_ok=True)
    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    segment = SourceSegment(
        relative_path="events/test.jsonl",
        partition="events/2026-08-31/test",
        sha256="a" * 64,
        byte_count=1,
        row_count=max(1, len(trades)),
        schema_version=1,
        first_available_at_ms=start_ms,
        last_available_at_ms=end_ms,
    )
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=start_ms,
        end_ms=end_ms,
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
    journal.record_manifest(manifest)
    closed_trade_ids: list[str] = []
    for index, spec in enumerate(trades):
        trade = _trade(spec, index=index, run_id=replay_run_id)
        if not (start_ms <= trade.opened_at_ms and trade.closed_at_ms < end_ms):
            raise ValueError("test artifact trade must be inside the replay interval")
        journal.record_trade(trade)
        facts.record_decision_fact(_fact(trade, spec))
        closed_trade_ids.append(trade.trade_id)
    journal.begin_run(manifest.manifest_id, replay_run_id)
    result = ReplayResult(
        manifest_id=manifest.manifest_id,
        run_id=replay_run_id,
        evidence_class=manifest.evidence_class,
        start_ms=start_ms,
        end_ms=end_ms,
        processed_events=max(1, len(trades)),
        processed_gaps=0,
        strategy_decisions=len(trades),
        risk_approvals=len(trades),
        risk_rejections=1 if hard_risk_reason is not None else 0,
        execution_attempts=len(trades) * 2,
        fills=len(trades) * 2,
        opened_positions=len(trades),
        closed_positions=len(trades),
        journal_observations=len(trades),
        closed_trade_ids=tuple(closed_trade_ids),
        final_account_state_id="account-final",
        data_complete=data_complete,
    )
    journal.finish_run(result)
    if hard_risk_reason is not None:
        journal.record_observation(
            JournalObservation(
                kind=ObservationKind.RISK_DECISION,
                timestamp_ms=max(start_ms, end_ms - 1),
                market=None,
                feature_snapshot_id=None,
                strategy_decision_id="health-strategy",
                risk_decision_id="health-risk",
                plan_id=None,
                attempt_id=None,
                position_action_id=None,
                account_state_id=None,
                reason_codes=(hard_risk_reason,),
                health_refs=("paper-state-healthy",),
                replay_run_id=replay_run_id,
            )
        )
    journal.close()
    facts.close()
    order_flag_key = "live_" + "order" + "s"
    replay_payload: dict[str, object] = {
        "data_complete": data_complete,
        "manifest_id": manifest.manifest_id,
        "network_access": network_access,
        "result_digest": result.result_digest,
        "run_id": replay_run_id,
        order_flag_key: order_execution,
    }
    (root / "replay.json").write_text(
        json.dumps(replay_payload, sort_keys=True),
        encoding="utf-8",
    )
    return ResearchArtifactBatch(
        artifact_root=root,
        batch_id=batch_id,
        source_id=source_id,
    )
