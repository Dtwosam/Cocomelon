from __future__ import annotations

from cocomelon.domain.evaluation import (
    AccountEquityFact,
    DecisionEvaluationFact,
    EquityFactKind,
)
from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.strategy import StrategyDecision
from cocomelon.execution.accounting import PaperAccountState


def decision_evaluation_fact(
    decision: StrategyDecision,
    feature: FeatureSnapshot,
    *,
    replay_run_id: str,
) -> DecisionEvaluationFact:
    if not replay_run_id.strip():
        raise ValueError("replay_run_id must not be empty")
    if decision.market != feature.market:
        raise ValueError("strategy decision market does not match feature market")
    if decision.feature_snapshot_id != feature.snapshot_id:
        raise ValueError("strategy decision feature snapshot does not match feature")
    if feature.as_of_ms > decision.timestamp_ms:
        raise ValueError("feature timestamp cannot be after strategy decision timestamp")
    if feature.source_received_at_ms > decision.timestamp_ms:
        raise ValueError("feature source timestamp cannot be after strategy decision timestamp")
    return DecisionEvaluationFact(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=feature.snapshot_id,
        replay_run_id=replay_run_id,
        market=decision.market,
        direction=decision.direction,
        timestamp_ms=decision.timestamp_ms,
        score=decision.score,
        lead_strategy=decision.lead_strategy,
        signal_ids=decision.signal_ids,
        reason_codes=decision.reason_codes,
        trend_regime=feature.trend_regime,
        volatility_regime=feature.volatility_regime,
    )


def account_equity_fact(
    account: PaperAccountState,
    *,
    replay_run_id: str,
    kind: EquityFactKind,
) -> AccountEquityFact:
    if not replay_run_id.strip():
        raise ValueError("replay_run_id must not be empty")
    return AccountEquityFact(
        replay_run_id=replay_run_id,
        account_state_id=account.state_id,
        timestamp_ms=account.updated_at_ms,
        kind=kind,
        equity=account.equity,
        cash=account.cash,
        unrealized_pnl=account.unrealized_pnl,
        realized_gross_pnl=account.realized_gross_pnl,
        cumulative_fees=account.cumulative_fees,
        cumulative_funding=account.cumulative_funding,
        gross_open_notional=account.gross_open_notional,
        open_position_count=len(account.positions),
    )
