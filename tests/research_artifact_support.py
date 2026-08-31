from __future__ import annotations

import hashlib
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
from cocomelon.evaluation.mainnet_evidence import (
    MAINNET_API_URL,
    MAINNET_EVIDENCE_KIND,
    MAINNET_WS_URL,
)
from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.evaluator import ResearchArtifactBatch

CODE_REVISION = "1" * 40
CONFIG_DIGEST = "c" * 64
TRIGGER_HEAD = "f" * 40


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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


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
    omit_fact_indices: tuple[int, ...] = (),
    code_revision: str = CODE_REVISION,
    config_digest: str = CONFIG_DIGEST,
) -> ResearchArtifactBatch:
    omitted = set(omit_fact_indices)
    if any(index < 0 or index >= len(trades) for index in omitted):
        raise ValueError("omit_fact_indices must reference an artifact trade")

    output = root / "output"
    recording = root / "recording"
    output.mkdir(parents=True, exist_ok=True)
    recording.mkdir(parents=True, exist_ok=True)

    segment_key = hashlib.sha256(replay_run_id.encode("utf-8")).hexdigest()[:16]
    relative_segment_path = f"events/{segment_key}.jsonl"
    physical_segment = recording / relative_segment_path
    physical_segment.parent.mkdir(parents=True, exist_ok=True)
    segment_bytes = (
        json.dumps(
            {
                "available_at_ms": start_ms,
                "event_kind": "test-mainnet-recording",
                "replay_run_id": replay_run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    physical_segment.write_bytes(segment_bytes)
    segment_sha = hashlib.sha256(segment_bytes).hexdigest()

    journal = JournalStore(output / "journal.sqlite3")
    facts = EvaluationFactStore(output / "facts.sqlite3")
    segment = SourceSegment(
        relative_path=relative_segment_path,
        partition=f"events/{segment_key}",
        sha256=segment_sha,
        byte_count=len(segment_bytes),
        row_count=1,
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
        code_revision=code_revision,
        config_digest=config_digest,
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
        if index not in omitted:
            facts.record_decision_fact(_fact(trade, spec))
        closed_trade_ids.append(trade.trade_id)
    journal.begin_run(manifest.manifest_id, replay_run_id)
    result = ReplayResult(
        manifest_id=manifest.manifest_id,
        run_id=replay_run_id,
        evidence_class=manifest.evidence_class,
        start_ms=start_ms,
        end_ms=end_ms,
        processed_events=1,
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

    session_id = hashlib.sha256(f"research-mainnet:{replay_run_id}".encode()).hexdigest()
    selected_markets = sorted({spec.market for spec in trades})
    _write_json(
        recording / "recording-session.json",
        {
            "api_url": MAINNET_API_URL,
            "ws_url": MAINNET_WS_URL,
            "recorder_code_revision": code_revision,
            "recording_config_digest": "e" * 64,
            "schema_version": 1,
            "selected": selected_markets,
            "selection_policy_id": "research-test-mainnet-v1",
            "session_id": session_id,
            "started_at_ms": start_ms,
        },
    )
    _write_json(
        output / "cohort-summary.json",
        {
            "checked_out_code_revision": code_revision,
            "closed_positions": result.closed_positions,
            "closed_trade_count": len(result.closed_trade_ids),
            "data_complete": data_complete,
            "dataset_manifest_id": "dataset-research-test",
            "dataset_trade_count": len(result.closed_trade_ids) - len(omitted),
            "economic_claim": "none",
            "evidence_kind": MAINNET_EVIDENCE_KIND,
            "excluded_trade_count": len(omitted),
            "execution_attempts": result.execution_attempts,
            "fills": result.fills,
            "final_equity": "10000",
            "opened_positions": result.opened_positions,
            "recorded_duplicate_count": 0,
            "recorded_event_count": 1,
            "recorded_gap_count": 0,
            "recording_session_id": session_id,
            "replay_result_digest": result.result_digest,
            "replay_run_id": result.run_id,
            "risk_approvals": result.risk_approvals,
            "risk_rejections": result.risk_rejections,
            "selected_markets": selected_markets,
            "strategy_decisions": result.strategy_decisions,
            "trigger_head_sha": TRIGGER_HEAD,
            "validated_segment_count": 1,
        },
    )
    _write_json(
        output / "record.json",
        {
            "anomaly_count": 0,
            "duplicate_count": 0,
            "duration_seconds": max(1, (end_ms - start_ms) // 1_000),
            "event_count": 1,
            "gap_count": 0,
            "live_orders": False,
            "network_access": True,
            "reconnect_count": 0,
            "root": "recording",
            "selected_markets": selected_markets,
            "session_id": session_id,
        },
    )
    order_flag_key = "live_" + "order" + "s"
    replay_payload: dict[str, object] = {
        "bundle_id": f"bundle-{replay_run_id}",
        "closed_positions": result.closed_positions,
        "closed_trade_ids": list(result.closed_trade_ids),
        "data_complete": data_complete,
        "evidence_class": manifest.evidence_class.value,
        "execution": "output/execution.sqlite3",
        "execution_attempts": result.execution_attempts,
        "facts": "output/facts.sqlite3",
        "fills": result.fills,
        "final_account_state_id": result.final_account_state_id,
        "final_equity": "10000",
        "journal": "output/journal.sqlite3",
        order_flag_key: order_execution,
        "manifest_id": manifest.manifest_id,
        "network_access": network_access,
        "opened_positions": result.opened_positions,
        "result_digest": result.result_digest,
        "risk_approvals": result.risk_approvals,
        "risk_rejections": result.risk_rejections,
        "run_id": replay_run_id,
        "strategy_decisions": result.strategy_decisions,
    }
    _write_json(output / "replay.json", replay_payload)
    _write_json(
        output / "freeze.json",
        {
            "bundle_id": f"bundle-{replay_run_id}",
            "code_revision": code_revision,
            "evidence_class": manifest.evidence_class.value,
            "live_orders": False,
            "manifest_id": manifest.manifest_id,
            "network_access": False,
            "out": "output/bundle.json",
            "recording_session_digest": session_id,
            "root": "recording",
            "source_set_digest": segment_sha,
            "starting_cash": "10000",
        },
    )
    _write_json(
        output / "bundle.json",
        {
            "bundle_id": f"bundle-{replay_run_id}",
            "manifest": {
                "code_revision": code_revision,
                "gap_refs": [],
                "manifest_id": manifest.manifest_id,
            },
            "recording_session_digest": session_id,
            "replay_config": {},
            "schema_version": 1,
            "source_locator_bundle_id": f"bundle-{replay_run_id}",
            "source_root_relative": "../recording",
            "source_set_digest": segment_sha,
        },
    )
    (output / "workflow-head.txt").write_text(code_revision + "\n", encoding="utf-8")
    (output / "trigger-head.txt").write_text(TRIGGER_HEAD + "\n", encoding="utf-8")
    return ResearchArtifactBatch(
        artifact_root=output,
        batch_id=batch_id,
        source_id=source_id,
    )
