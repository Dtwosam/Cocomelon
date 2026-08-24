from decimal import ROUND_UP, Context, Decimal, localcontext

import pytest
from cocomelon.domain.evaluation import (
    AccountEquityFact,
    CandidateDefinition,
    ConfidenceInterval,
    DecisionEvaluationFact,
    EdgeEvidenceStatus,
    EquityFactKind,
    EvaluationDatasetManifest,
    EvaluationPolicy,
    FrozenCandidateSet,
    FrozenSplitManifest,
    OOSStatus,
    PerformanceMetrics,
    PromotionGatePreview,
    ReplayEvaluationSource,
    SplitName,
    TimePartition,
    TradeEvaluationSample,
)

from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction

MARKET = MarketId("", "SOL")


def decision_fact(*, score: Decimal = Decimal("72.5")) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id="strategy-1",
        feature_snapshot_id="feature-1",
        replay_run_id="run-1",
        market=MARKET,
        direction=Direction.LONG,
        timestamp_ms=1_000,
        score=score,
        lead_strategy="trend",
        signal_ids=("signal-b", "signal-a"),
        reason_codes=("trend", "liquid"),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def source(*, result_digest: str = "a" * 64) -> ReplayEvaluationSource:
    return ReplayEvaluationSource(
        run_id="run-1",
        manifest_id="manifest-1",
        result_digest=result_digest,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=10_000,
        data_complete=True,
    )


def dataset_manifest(
    *,
    trade_ids: tuple[str, ...] = ("trade-b", "trade-a"),
    result_digest: str = "a" * 64,
) -> EvaluationDatasetManifest:
    return EvaluationDatasetManifest(
        sources=(source(result_digest=result_digest),),
        trade_ids=trade_ids,
        decision_fact_ids=("fact-b", "fact-a"),
        equity_fact_ids=("equity-b", "equity-a"),
        start_ms=0,
        end_ms=10_000,
        code_revision="phase9-test",
        data_complete=True,
        gap_refs=(),
        mixed_evidence_diagnostic=False,
    )


def policy() -> EvaluationPolicy:
    return EvaluationPolicy()


def split_manifest() -> FrozenSplitManifest:
    return FrozenSplitManifest(
        dataset_manifest_id=dataset_manifest().manifest_id,
        train=TimePartition(SplitName.TRAIN, 0, 1_000),
        validation=TimePartition(SplitName.VALIDATION, 2_000, 3_000),
        test=TimePartition(SplitName.TEST, 4_000, 10_000),
        embargo_ms=500,
        policy_id=policy().policy_id,
    )


def candidate(*, version: str = "phase5-v1") -> CandidateDefinition:
    return CandidateDefinition(
        name="baseline",
        strategy_version=version,
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        code_revision="abc123",
        config_digest="c" * 64,
    )


def metrics() -> PerformanceMetrics:
    return PerformanceMetrics(
        trade_count=2,
        covered_days=2,
        gross_pnl=Decimal("12"),
        total_fees=Decimal("1"),
        funding_cash_pnl=Decimal("0"),
        signed_slippage_amount=Decimal("1"),
        net_pnl=Decimal("11"),
        total_net_r=Decimal("1.1"),
        mean_net_r=Decimal("0.55"),
        median_net_r=Decimal("0.55"),
        win_rate=Decimal("0.5"),
        average_winner_r=Decimal("1.2"),
        average_loser_r=Decimal("-0.1"),
        profit_factor=Decimal("12"),
        profit_factor_unavailable_reason=None,
        largest_winner_r=Decimal("1.2"),
        largest_loser_r=Decimal("-0.1"),
        p05_net_r=Decimal("-0.1"),
        expected_shortfall_5pct=Decimal("-0.1"),
        median_holding_duration_ms=1_000,
        p95_holding_duration_ms=2_000,
        realized_closed_trade_max_drawdown_fraction=Decimal("0.01"),
        account_equity_max_drawdown_fraction=None,
        account_drawdown_unavailable_reason="INCOMPLETE_EQUITY_CURVE",
        max_market_positive_pnl_share=Decimal("0.5"),
        max_strategy_positive_pnl_share=Decimal("0.5"),
        max_seven_day_positive_pnl_share=Decimal("0.5"),
    )


def test_decision_fact_id_ignores_ambient_decimal_context() -> None:
    expected = decision_fact().fact_id

    with localcontext(Context(prec=5, rounding=ROUND_UP)):
        assert decision_fact().fact_id == expected


def test_decision_fact_canonicalizes_set_like_signal_ids() -> None:
    first = decision_fact()
    second = DecisionEvaluationFact(
        strategy_decision_id=first.strategy_decision_id,
        feature_snapshot_id=first.feature_snapshot_id,
        replay_run_id=first.replay_run_id,
        market=first.market,
        direction=first.direction,
        timestamp_ms=first.timestamp_ms,
        score=first.score,
        lead_strategy=first.lead_strategy,
        signal_ids=("signal-a", "signal-b", "signal-a"),
        reason_codes=first.reason_codes,
        trend_regime=first.trend_regime,
        volatility_regime=first.volatility_regime,
    )

    assert first.fact_id == second.fact_id
    assert second.signal_ids == ("signal-a", "signal-b")


def test_dataset_manifest_canonicalizes_input_enumeration() -> None:
    first = dataset_manifest(trade_ids=("trade-b", "trade-a"))
    second = dataset_manifest(trade_ids=("trade-a", "trade-b"))

    assert first.manifest_id == second.manifest_id
    assert first.trade_ids == ("trade-a", "trade-b")


def test_dataset_manifest_changes_when_source_result_digest_changes() -> None:
    first = dataset_manifest(result_digest="a" * 64)
    second = dataset_manifest(result_digest="b" * 64)

    assert first.manifest_id != second.manifest_id


def test_policy_has_locked_phase9_v1_readiness_defaults() -> None:
    item = policy()

    assert item.policy_version == "phase9-v1"
    assert item.min_oos_trades == 100
    assert item.min_oos_days == 30
    assert item.min_walkforward_windows == 3
    assert item.min_trades_per_walkforward_window == 20
    assert item.min_score_bucket_trades == 20
    assert item.positive_walkforward_fraction == Decimal("0.60")
    assert item.bootstrap_confidence == Decimal("0.95")
    assert item.bootstrap_block_days == 5
    assert item.bootstrap_resamples == 2_000
    assert item.split_embargo_ms == 21_600_000
    assert item.no_trade_horizons_ms == (3_600_000, 14_400_000)


def test_policy_id_changes_when_a_readiness_gate_changes() -> None:
    first = policy()
    second = EvaluationPolicy(min_oos_trades=101)

    assert first.policy_id != second.policy_id


def test_time_partitions_and_split_order_are_validated() -> None:
    assert split_manifest().test.name is SplitName.TEST

    with pytest.raises(ValueError, match="partition"):
        TimePartition(SplitName.TRAIN, 1_000, 1_000)

    with pytest.raises(ValueError, match="ordered"):
        FrozenSplitManifest(
            dataset_manifest_id=dataset_manifest().manifest_id,
            train=TimePartition(SplitName.TRAIN, 0, 5_000),
            validation=TimePartition(SplitName.VALIDATION, 4_000, 6_000),
            test=TimePartition(SplitName.TEST, 7_000, 10_000),
            embargo_ms=0,
            policy_id=policy().policy_id,
        )


def test_candidate_set_is_canonical_and_semantic() -> None:
    first = FrozenCandidateSet(
        candidates=(candidate(version="v2"), candidate(version="v1")),
        sensitivity_profile_ids=("combined_stress", "base"),
    )
    second = FrozenCandidateSet(
        candidates=(candidate(version="v1"), candidate(version="v2")),
        sensitivity_profile_ids=("base", "combined_stress"),
    )

    assert first.candidate_set_id == second.candidate_set_id
    assert first.candidates == second.candidates


def test_account_equity_fact_requires_finite_positive_equity() -> None:
    with pytest.raises(ValueError, match="equity"):
        AccountEquityFact(
            replay_run_id="run-1",
            account_state_id="state-1",
            timestamp_ms=1_000,
            kind=EquityFactKind.MARK,
            equity=Decimal("NaN"),
            cash=Decimal("100"),
            unrealized_pnl=Decimal("0"),
            realized_gross_pnl=Decimal("0"),
            cumulative_fees=Decimal("0"),
            cumulative_funding=Decimal("0"),
            gross_open_notional=Decimal("0"),
            open_position_count=0,
        )


def test_trade_sample_rejects_nonfinite_financial_values() -> None:
    with pytest.raises(ValueError, match="net_pnl"):
        TradeEvaluationSample(
            trade_id="trade-1",
            replay_run_id="run-1",
            strategy_decision_id="strategy-1",
            market=MARKET,
            direction=Direction.LONG,
            decision_timestamp_ms=900,
            opened_at_ms=1_000,
            closed_at_ms=2_000,
            score=Decimal("70"),
            lead_strategy="trend",
            trend_regime=TrendRegime.UP,
            volatility_regime=VolatilityRegime.NORMAL,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            gross_realized_pnl=Decimal("10"),
            entry_fees=Decimal("1"),
            exit_fees=Decimal("1"),
            funding_cash_pnl=Decimal("0"),
            net_pnl=Decimal("NaN"),
            entry_slippage_amount=Decimal("0"),
            exit_slippage_amount=Decimal("0"),
            net_r=Decimal("0.4"),
            equity_before=Decimal("10000"),
            equity_after=Decimal("10008"),
            holding_duration_ms=1_000,
            reason_codes=(),
        )


def test_confidence_interval_requires_ordered_finite_bounds() -> None:
    with pytest.raises(ValueError, match="bounds"):
        ConfidenceInterval(
            metric="mean_net_r",
            lower=Decimal("1"),
            upper=Decimal("0"),
            confidence=Decimal("0.95"),
            resamples=2_000,
            block_days=5,
        )


def test_profit_factor_unavailable_requires_reason() -> None:
    kwargs = {
        field: getattr(metrics(), field)
        for field in metrics().__dataclass_fields__
    }
    kwargs["profit_factor"] = None
    kwargs["profit_factor_unavailable_reason"] = None

    with pytest.raises(ValueError, match="profit_factor_unavailable_reason"):
        PerformanceMetrics(**kwargs)


def test_promotion_preview_is_permanently_read_only() -> None:
    preview = PromotionGatePreview(
        profit_factor_pass=True,
        max_drawdown_pass=None,
        market_concentration_pass=True,
        seven_day_concentration_pass=True,
        closed_trade_count_pass=False,
        covered_days_pass=False,
        invariant_health_pass=None,
        reason_codes=("INSUFFICIENT_SHADOW_DAYS",),
    )

    assert preview.preview_only is True


def test_edge_status_and_oos_status_include_fail_closed_outcomes() -> None:
    assert EdgeEvidenceStatus.NO_EDGE_DEMONSTRATED.value == "no_edge_demonstrated"
    assert EdgeEvidenceStatus.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"
    assert OOSStatus.CONTAMINATED.value == "contaminated"
