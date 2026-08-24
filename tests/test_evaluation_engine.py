from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import (
    CandidateDefinition,
    ConfidenceInterval,
    EdgeEvidenceStatus,
    EvaluationPolicy,
    FrozenCandidateSet,
    OOSStatus,
    PerformanceMetrics,
    SplitName,
    TimePartition,
    WalkForwardWindowResult,
)
from cocomelon.evaluation.engine import build_promotion_preview, derive_edge_status


def metrics(
    *,
    trades: int = 120,
    days: int = 30,
    mean_r: str = "0.10",
    market_share: str | None = "0.34",
    seven_day_share: str | None = "0.40",
    profit_factor: str | None = "1.25",
    account_drawdown: str | None = "0.07",
) -> PerformanceMetrics:
    mean = Decimal(mean_r)
    pf = None if profit_factor is None else Decimal(profit_factor)
    drawdown = None if account_drawdown is None else Decimal(account_drawdown)
    return PerformanceMetrics(
        trade_count=trades,
        covered_days=days,
        gross_pnl=Decimal("100"),
        total_fees=Decimal("10"),
        funding_cash_pnl=Decimal("0"),
        signed_slippage_amount=Decimal("5"),
        net_pnl=Decimal("85"),
        total_net_r=mean * Decimal(trades),
        mean_net_r=mean,
        median_net_r=mean,
        win_rate=Decimal("0.55"),
        average_winner_r=Decimal("0.2"),
        average_loser_r=Decimal("-0.1"),
        profit_factor=pf,
        profit_factor_unavailable_reason=None if pf is not None else "NO_LOSING_TRADES",
        largest_winner_r=Decimal("0.4"),
        largest_loser_r=Decimal("-0.3"),
        p05_net_r=Decimal("-0.2"),
        expected_shortfall_5pct=Decimal("-0.25"),
        median_holding_duration_ms=1_000,
        p95_holding_duration_ms=2_000,
        realized_closed_trade_max_drawdown_fraction=Decimal("0.04"),
        account_equity_max_drawdown_fraction=drawdown,
        account_drawdown_unavailable_reason=None if drawdown is not None else "NO_EQUITY_FACTS",
        max_market_positive_pnl_share=(
            None if market_share is None else Decimal(market_share)
        ),
        max_strategy_positive_pnl_share=Decimal("0.50"),
        max_seven_day_positive_pnl_share=(
            None if seven_day_share is None else Decimal(seven_day_share)
        ),
    )


def interval(*, lower: str = "0.02", upper: str = "0.18") -> ConfidenceInterval:
    return ConfidenceInterval(
        metric="mean_net_r",
        lower=Decimal(lower),
        upper=Decimal(upper),
        confidence=Decimal("0.95"),
        resamples=2_000,
        block_days=5,
    )


def window(
    suffix: int,
    *,
    mean_r: str = "0.10",
    trades: int = 20,
    eligible: bool = True,
) -> WalkForwardWindowResult:
    values = metrics(trades=trades, days=5, mean_r=mean_r)
    return WalkForwardWindowResult(
        split_manifest_id=f"split-{suffix}",
        evaluation_start_ms=suffix * 10_000,
        evaluation_end_ms=(suffix + 1) * 10_000,
        included_trade_ids=tuple(f"trade-{suffix}-{index}" for index in range(trades)),
        excluded_trade_ids=(),
        metrics=values,
        eligible=eligible,
        reason_codes=() if eligible else ("INSUFFICIENT_WALKFORWARD_TRADES",),
    )


def stable_windows() -> tuple[WalkForwardWindowResult, ...]:
    return (window(1), window(2), window(3))


def test_edge_status_matrix_is_fail_closed() -> None:
    rules = EvaluationPolicy()
    ready = metrics()
    stable = stable_windows()

    assert (
        derive_edge_status(
            evidence_valid=False,
            oos_status=OOSStatus.UNTOUCHED,
            test_metrics=ready,
            confidence_interval=interval(),
            walkforward_results=stable,
            policy=rules,
        )
        is EdgeEvidenceStatus.INVALID_EVIDENCE
    )
    assert (
        derive_edge_status(
            evidence_valid=True,
            oos_status=OOSStatus.CONTAMINATED,
            test_metrics=ready,
            confidence_interval=interval(),
            walkforward_results=stable,
            policy=rules,
        )
        is EdgeEvidenceStatus.OOS_CONTAMINATED
    )
    assert (
        derive_edge_status(
            evidence_valid=True,
            oos_status=OOSStatus.UNTOUCHED,
            test_metrics=metrics(trades=99),
            confidence_interval=None,
            walkforward_results=stable,
            policy=rules,
        )
        is EdgeEvidenceStatus.INSUFFICIENT_EVIDENCE
    )
    assert (
        derive_edge_status(
            evidence_valid=True,
            oos_status=OOSStatus.UNTOUCHED,
            test_metrics=ready,
            confidence_interval=interval(lower="0"),
            walkforward_results=stable,
            policy=rules,
        )
        is EdgeEvidenceStatus.NO_EDGE_DEMONSTRATED
    )
    assert (
        derive_edge_status(
            evidence_valid=True,
            oos_status=OOSStatus.REPRODUCTION,
            test_metrics=ready,
            confidence_interval=interval(),
            walkforward_results=stable,
            policy=rules,
        )
        is EdgeEvidenceStatus.CANDIDATE_EDGE
    )


def test_concentration_blocks_candidate_edge() -> None:
    rules = EvaluationPolicy()
    stable = stable_windows()

    for concentrated in (
        metrics(market_share="0.3500001"),
        metrics(seven_day_share="0.5000001"),
    ):
        assert (
            derive_edge_status(
                evidence_valid=True,
                oos_status=OOSStatus.UNTOUCHED,
                test_metrics=concentrated,
                confidence_interval=interval(),
                walkforward_results=stable,
                policy=rules,
            )
            is EdgeEvidenceStatus.NO_EDGE_DEMONSTRATED
        )


def test_promotion_preview_uses_locked_live_thresholds_only_as_preview() -> None:
    passing = build_promotion_preview(
        metrics(
            trades=500,
            days=45,
            profit_factor="1.20",
            account_drawdown="0.08",
            market_share="0.35",
            seven_day_share="0.50",
        ),
        invariant_health_pass=True,
    )

    assert passing.preview_only is True
    assert passing.profit_factor_pass is True
    assert passing.max_drawdown_pass is True
    assert passing.market_concentration_pass is True
    assert passing.seven_day_concentration_pass is True
    assert passing.closed_trade_count_pass is True
    assert passing.covered_days_pass is True
    assert passing.invariant_health_pass is True

    failing = build_promotion_preview(
        metrics(
            trades=499,
            days=44,
            profit_factor="1.1999",
            account_drawdown="0.0801",
            market_share="0.3501",
            seven_day_share="0.5001",
        ),
        invariant_health_pass=False,
    )
    assert failing.preview_only is True
    assert failing.profit_factor_pass is False
    assert failing.max_drawdown_pass is False
    assert failing.market_concentration_pass is False
    assert failing.seven_day_concentration_pass is False
    assert failing.closed_trade_count_pass is False
    assert failing.covered_days_pass is False
    assert failing.invariant_health_pass is False


def test_candidate_and_split_contracts_can_be_frozen_to_same_policy() -> None:
    rules = EvaluationPolicy()
    candidate_set = FrozenCandidateSet(
        candidates=(
            CandidateDefinition(
                name="baseline",
                strategy_version="phase5-v1",
                risk_version="phase6-v1",
                execution_config_version="phase7-v1",
                code_revision="phase9-test",
                config_digest="c" * 64,
            ),
        ),
        sensitivity_profile_ids=("base", "combined_stress"),
        policy_id=rules.policy_id,
    )
    train = TimePartition(SplitName.TRAIN, 0, 10_000)
    validation = TimePartition(SplitName.VALIDATION, 10_000, 20_000)
    test = TimePartition(SplitName.TEST, 20_000, 30_000)

    assert candidate_set.policy_id == rules.policy_id
    assert train.end_ms == validation.start_ms
    assert validation.end_ms == test.start_ms


def test_engine_module_is_offline_only() -> None:
    source = Path("src/cocomelon/evaluation/engine.py").read_text(encoding="utf-8").lower()

    for forbidden in (
        "hyperliquid",
        "websocket",
        "httpx",
        "requests",
        "private_key",
        "signing",
        "place_order",
        "cancel_order",
        "testnet",
    ):
        assert forbidden not in source
