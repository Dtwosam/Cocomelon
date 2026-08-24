from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.evaluation import (
    ConfidenceInterval,
    EdgeEvidenceStatus,
    EvaluationPolicy,
    OOSStatus,
    PerformanceMetrics,
    PromotionGatePreview,
    WalkForwardWindowResult,
)

ZERO = Decimal("0")
MARKET_CONCENTRATION_LIMIT = Decimal("0.35")
SEVEN_DAY_CONCENTRATION_LIMIT = Decimal("0.50")
LIVE_PROFIT_FACTOR_LIMIT = Decimal("1.20")
LIVE_DRAWDOWN_LIMIT = Decimal("0.08")
LIVE_TRADE_COUNT = 500
LIVE_COVERED_DAYS = 45
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


def _eligible_walkforward(
    results: Sequence[WalkForwardWindowResult],
) -> tuple[WalkForwardWindowResult, ...]:
    return tuple(item for item in results if item.eligible)


def derive_edge_status(
    *,
    evidence_valid: bool,
    oos_status: OOSStatus,
    test_metrics: PerformanceMetrics,
    confidence_interval: ConfidenceInterval | None,
    walkforward_results: Sequence[WalkForwardWindowResult],
    policy: EvaluationPolicy,
) -> EdgeEvidenceStatus:
    if not evidence_valid:
        return EdgeEvidenceStatus.INVALID_EVIDENCE
    if oos_status is OOSStatus.CONTAMINATED:
        return EdgeEvidenceStatus.OOS_CONTAMINATED

    eligible = _eligible_walkforward(walkforward_results)
    if (
        test_metrics.trade_count < policy.min_oos_trades
        or test_metrics.covered_days < policy.min_oos_days
        or confidence_interval is None
        or len(eligible) < policy.min_walkforward_windows
    ):
        return EdgeEvidenceStatus.INSUFFICIENT_EVIDENCE

    with localcontext(AUTHORITATIVE_CONTEXT):
        aggregate_trade_count = sum(item.metrics.trade_count for item in eligible)
        aggregate_net_r = sum((item.metrics.total_net_r for item in eligible), ZERO)
        aggregate_mean_net_r = (
            ZERO
            if aggregate_trade_count == 0
            else aggregate_net_r / Decimal(aggregate_trade_count)
        )
        positive_fraction = Decimal(
            sum(item.metrics.mean_net_r > ZERO for item in eligible)
        ) / Decimal(len(eligible))

    if (
        test_metrics.mean_net_r <= ZERO
        or confidence_interval.lower <= ZERO
        or aggregate_mean_net_r <= ZERO
        or positive_fraction < policy.positive_walkforward_fraction
        or test_metrics.max_market_positive_pnl_share is None
        or test_metrics.max_market_positive_pnl_share > MARKET_CONCENTRATION_LIMIT
        or test_metrics.max_seven_day_positive_pnl_share is None
        or test_metrics.max_seven_day_positive_pnl_share > SEVEN_DAY_CONCENTRATION_LIMIT
    ):
        return EdgeEvidenceStatus.NO_EDGE_DEMONSTRATED

    return EdgeEvidenceStatus.CANDIDATE_EDGE


def build_promotion_preview(
    metrics: PerformanceMetrics,
    *,
    invariant_health_pass: bool | None,
) -> PromotionGatePreview:
    profit_factor_pass = (
        None
        if metrics.profit_factor is None
        else metrics.profit_factor >= LIVE_PROFIT_FACTOR_LIMIT
    )
    max_drawdown_pass = (
        None
        if metrics.account_equity_max_drawdown_fraction is None
        else metrics.account_equity_max_drawdown_fraction <= LIVE_DRAWDOWN_LIMIT
    )
    market_concentration_pass = (
        None
        if metrics.max_market_positive_pnl_share is None
        else metrics.max_market_positive_pnl_share <= MARKET_CONCENTRATION_LIMIT
    )
    seven_day_concentration_pass = (
        None
        if metrics.max_seven_day_positive_pnl_share is None
        else metrics.max_seven_day_positive_pnl_share <= SEVEN_DAY_CONCENTRATION_LIMIT
    )

    reasons: list[str] = []
    checks = (
        ("PROFIT_FACTOR", profit_factor_pass),
        ("ACCOUNT_DRAWDOWN", max_drawdown_pass),
        ("MARKET_CONCENTRATION", market_concentration_pass),
        ("SEVEN_DAY_CONCENTRATION", seven_day_concentration_pass),
        ("CLOSED_TRADE_COUNT", metrics.trade_count >= LIVE_TRADE_COUNT),
        ("COVERED_DAYS", metrics.covered_days >= LIVE_COVERED_DAYS),
        ("INVARIANT_HEALTH", invariant_health_pass),
    )
    for label, result in checks:
        if result is None:
            reasons.append(f"{label}_UNAVAILABLE")
        elif not result:
            reasons.append(f"{label}_FAIL")

    return PromotionGatePreview(
        profit_factor_pass=profit_factor_pass,
        max_drawdown_pass=max_drawdown_pass,
        market_concentration_pass=market_concentration_pass,
        seven_day_concentration_pass=seven_day_concentration_pass,
        closed_trade_count_pass=metrics.trade_count >= LIVE_TRADE_COUNT,
        covered_days_pass=metrics.covered_days >= LIVE_COVERED_DAYS,
        invariant_health_pass=invariant_health_pass,
        reason_codes=tuple(reasons),
    )
