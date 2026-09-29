from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.execution import OrderSide, OrderType, PaperOrderPlan
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_learning import (
    CONTINUOUS_PAPER_REPLAY_RUN_ID,
    ContinuousPaperOpeningLineage,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    CapacityReleaseOpportunityOption,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    candidate_caused_capacity_release_options,
    prospective_capacity_reflow_release_lineage_summary,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _plan(
    market: str,
    *,
    direction: Direction,
    strategy_decision_id: str,
    created_at_ms: int,
) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id=f"risk-{market}",
        strategy_decision_id=strategy_decision_id,
        market=_market(market),
        side=(
            OrderSide.BUY
            if direction is Direction.LONG
            else OrderSide.SELL
        ),
        requested_quantity=Decimal("1"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=created_at_ms,
        earliest_execution_ms=created_at_ms,
        execution_config_version="fixture",
        instrument_metadata_received_at_ms=created_at_ms,
        approved_risk_amount_ceiling=Decimal("25"),
        stop_distance_fraction=Decimal("0.1"),
        effective_loss_fraction=Decimal("0.102"),
    )


def _fact(
    market: str,
    *,
    direction: Direction,
    strategy_decision_id: str,
    feature_snapshot_id: str,
    lead_strategy: str,
    timestamp_ms: int,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=strategy_decision_id,
        feature_snapshot_id=feature_snapshot_id,
        replay_run_id=CONTINUOUS_PAPER_REPLAY_RUN_ID,
        market=_market(market),
        direction=direction,
        timestamp_ms=timestamp_ms,
        score=Decimal("0.7"),
        lead_strategy=lead_strategy,
        signal_ids=(f"signal-{market}",),
        reason_codes=("decision_threshold_met",),
        trend_regime=(
            TrendRegime.UP
            if direction is Direction.LONG
            else TrendRegime.DOWN
        ),
        volatility_regime=VolatilityRegime.NORMAL,
    )


def _rank(
    plan: PaperOrderPlan,
    *,
    opened_at_ms: int,
    ordinal: int,
) -> ContinuousPaperOpeningRankEvidence:
    return ContinuousPaperOpeningRankEvidence(
        opening_plan_id=plan.plan_id,
        market=plan.market.canonical,
        opened_at_ms=opened_at_ms,
        rank_observed_at_ms=opened_at_ms - 100,
        rank_age_ms=100,
        ordinal=ordinal,
        score=Decimal("0.8"),
        rank_pool_size=20,
        reason_codes=("fixture",),
    )


def test_release_lineage_proves_candidate_filtered_capacity_source() -> None:
    opportunity_id = "opportunity-sol"
    opportunity_timestamp_ms = 20_000
    btc_plan = _plan(
        "BTC",
        direction=Direction.LONG,
        strategy_decision_id="strategy-btc",
        created_at_ms=9_900,
    )
    eth_plan = _plan(
        "ETH",
        direction=Direction.SHORT,
        strategy_decision_id="strategy-eth",
        created_at_ms=10_900,
    )
    runtime = ContinuousPaperRuntimeIdentity(
        worker_run_id=123,
        worker_run_attempt=1,
        worker_head_sha="a" * 40,
    )
    lineages = (
        ContinuousPaperOpeningLineage(
            opening_plan_id=btc_plan.plan_id,
            feature_snapshot_id="feature-btc",
            market="BTC",
            opened_at_ms=10_000,
            runtime=runtime,
        ),
        ContinuousPaperOpeningLineage(
            opening_plan_id=eth_plan.plan_id,
            feature_snapshot_id="feature-eth",
            market="ETH",
            opened_at_ms=11_000,
            runtime=runtime,
        ),
    )
    options = (
        CapacityReleaseOpportunityOption(
            opportunity_id=opportunity_id,
            opportunity_timestamp_ms=opportunity_timestamp_ms,
            opportunity_market="SOL",
            release_market="BTC",
            release_correlation_bucket="majors",
        ),
        CapacityReleaseOpportunityOption(
            opportunity_id=opportunity_id,
            opportunity_timestamp_ms=opportunity_timestamp_ms,
            opportunity_market="SOL",
            release_market="ETH",
            release_correlation_bucket="majors",
        ),
    )
    plans = {
        btc_plan.plan_id: btc_plan,
        eth_plan.plan_id: eth_plan,
    }
    facts = {
        ("strategy-btc", CONTINUOUS_PAPER_REPLAY_RUN_ID): _fact(
            "BTC",
            direction=Direction.LONG,
            strategy_decision_id="strategy-btc",
            feature_snapshot_id="feature-btc",
            lead_strategy="trend",
            timestamp_ms=9_000,
        ),
        ("strategy-eth", CONTINUOUS_PAPER_REPLAY_RUN_ID): _fact(
            "ETH",
            direction=Direction.SHORT,
            strategy_decision_id="strategy-eth",
            feature_snapshot_id="feature-eth",
            lead_strategy="breakout",
            timestamp_ms=10_000,
        ),
    }
    ranks = {
        btc_plan.plan_id: _rank(
            btc_plan,
            opened_at_ms=10_000,
            ordinal=5,
        ),
        eth_plan.plan_id: _rank(
            eth_plan,
            opened_at_ms=11_000,
            ordinal=4,
        ),
    }

    result = prospective_capacity_reflow_release_lineage_summary(
        options,
        lineages,
        (),
        plan_loader=plans.get,
        fact_loader=lambda strategy_id, replay_run_id: facts.get(
            (strategy_id, replay_run_id)
        ),
        rank_loader=ranks.get,
        state=ProspectiveCombinedEntryFilterState(started_at_ms=0),
    )

    caused = candidate_caused_capacity_release_options(
        options,
        lineages,
        (),
        plan_loader=plans.get,
        fact_loader=lambda strategy_id, replay_run_id: facts.get(
            (strategy_id, replay_run_id)
        ),
        rank_loader=ranks.get,
    )
    assert caused == (options[0],)

    assert result["release_options"] == 2
    assert result["resolved_release_options"] == 2
    assert result["resolved_opportunities"] == 1
    assert result["candidate_blocked_release_options"] == 1
    assert result["candidate_allowed_release_options"] == 1
    assert result["candidate_capacity_release_opportunities"] == 1
    assert result["release_lineage_misses"] == 0
    assert result["release_plan_misses"] == 0
    assert result["release_decision_misses"] == 0
    assert result["release_rank_misses"] == 0
    assert result["release_stale_ranks"] == 0
    assert result["integrity_clean"] is True
    assert result["by_release_position_block_reason"] == {
        "long_trend": 1
    }
    assert result["by_candidate_blocked_release_market"] == {
        "BTC": 1
    }
    assert result["replacement_trades_modeled"] is False
    assert result["pnl_modeled"] is False


def test_release_lineage_reports_missing_historical_position() -> None:
    result = prospective_capacity_reflow_release_lineage_summary(
        (
            CapacityReleaseOpportunityOption(
                opportunity_id="opportunity-sol",
                opportunity_timestamp_ms=20_000,
                opportunity_market="SOL",
                release_market="BTC",
                release_correlation_bucket="majors",
            ),
        ),
        (),
        (),
        plan_loader=lambda _plan_id: None,
        fact_loader=lambda _strategy_id, _run_id: None,
        rank_loader=lambda _plan_id: None,
        state=ProspectiveCombinedEntryFilterState(started_at_ms=0),
    )

    assert result["release_options"] == 1
    assert result["resolved_release_options"] == 0
    assert result["candidate_capacity_release_opportunities"] == 0
    assert result["release_lineage_misses"] == 1
    assert result["integrity_clean"] is False
