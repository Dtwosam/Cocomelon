from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Final, cast

COMMON_FROZEN_STARTED_AT_MS: Final = 1_791_193_533_061
FIVE_MINUTE_HORIZON_MS: Final = 300_000
FIFTEEN_MINUTE_HORIZON_MS: Final = 900_000
MIN_PAIRED_OPTIONS: Final = 12
MIN_MARKETS: Final = 4
ZERO: Final = Decimal("0")


class ProspectiveLongTrendExactHorizonComparisonError(RuntimeError):
    pass


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ProspectiveLongTrendExactHorizonComparisonError(
            f"{field} must be a decimal string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveLongTrendExactHorizonComparisonError(
            f"{field} must be a decimal string"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveLongTrendExactHorizonComparisonError(
            f"{field} must be finite"
        )
    return parsed


def _validate_summary(
    raw: object,
    *,
    horizon_ms: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendExactHorizonComparisonError(
            "exact-horizon summary must be an object"
        )
    for key, expected in (
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_execution", False),
        ("changes_risk_limits", False),
        ("changes_candidate_readiness", False),
        ("discovery_cohort_reused_for_validation", False),
        ("cross_horizon_selection_frozen", True),
    ):
        if raw.get(key) is not expected:
            raise ProspectiveLongTrendExactHorizonComparisonError(
                f"exact-horizon authority drift: {key}"
            )
    if raw.get("started_at_ms") != COMMON_FROZEN_STARTED_AT_MS:
        raise ProspectiveLongTrendExactHorizonComparisonError(
            "exact-horizon freeze does not match common comparison boundary"
        )
    if raw.get("exit_horizon_ms") != horizon_ms:
        raise ProspectiveLongTrendExactHorizonComparisonError(
            "exact-horizon summary uses the wrong exit horizon"
        )
    digest = raw.get("execution_config_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ProspectiveLongTrendExactHorizonComparisonError(
            "exact-horizon execution-config digest is invalid"
        )
    rows = raw.get("option_results")
    if not isinstance(rows, list):
        raise ProspectiveLongTrendExactHorizonComparisonError(
            "exact-horizon option results must be a list"
        )
    return raw


def _option_index(
    summary: dict[str, object],
) -> dict[str, dict[str, object]]:
    raw_rows = cast(list[object], summary["option_results"])
    output: dict[str, dict[str, object]] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ProspectiveLongTrendExactHorizonComparisonError(
                "exact-horizon option result must be an object"
            )
        opportunity_id = raw.get("opportunity_id")
        timestamp_ms = raw.get("timestamp_ms")
        market = raw.get("market")
        direction = raw.get("direction")
        if (
            not isinstance(opportunity_id, str)
            or not opportunity_id
            or isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or not isinstance(market, str)
            or not market
            or direction != "long"
        ):
            raise ProspectiveLongTrendExactHorizonComparisonError(
                "exact-horizon option lineage is invalid"
            )
        if opportunity_id in output:
            raise ProspectiveLongTrendExactHorizonComparisonError(
                "duplicate exact-horizon opportunity id"
            )
        pnl = raw.get("exact_realized_pnl")
        return_fraction = raw.get("exact_realized_return_fraction")
        if pnl is not None:
            _decimal(pnl, "exact_realized_pnl")
            _decimal(
                return_fraction,
                "exact_realized_return_fraction",
            )
        elif return_fraction is not None:
            raise ProspectiveLongTrendExactHorizonComparisonError(
                "exact return fraction requires exact realized pnl"
            )
        output[opportunity_id] = raw
    return output


def _incomplete_reason_counts(
    index: dict[str, dict[str, object]],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in index.values():
        if row.get("exact_realized_pnl") is not None:
            continue
        reason = row.get("incomplete_reason")
        key = reason if isinstance(reason, str) and reason else "unspecified"
        counts[key] += 1
    return dict(sorted(counts.items()))


def _leave_one_trade_totals(deltas: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    if len(deltas) <= 1:
        return ()
    total = sum(deltas, ZERO)
    return tuple(total - value for value in deltas)


def _leave_one_market_totals(
    rows: tuple[dict[str, object], ...],
    *,
    delta_key: str = "pnl_delta_5m_minus_15m",
) -> tuple[Decimal, ...]:
    by_market: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total = ZERO
    for row in rows:
        market = cast(str, row["market"])
        delta = _decimal(row[delta_key], f"paired {delta_key}")
        by_market[market] += delta
        total += delta
    if len(by_market) <= 1:
        return ()
    return tuple(
        total - by_market[market]
        for market in sorted(by_market)
    )


def prospective_long_trend_exact_horizon_comparison(
    five_minute_raw: object,
    fifteen_minute_raw: object,
) -> dict[str, object]:
    five = _validate_summary(
        five_minute_raw,
        horizon_ms=FIVE_MINUTE_HORIZON_MS,
    )
    fifteen = _validate_summary(
        fifteen_minute_raw,
        horizon_ms=FIFTEEN_MINUTE_HORIZON_MS,
    )
    if five["execution_config_sha256"] != fifteen["execution_config_sha256"]:
        raise ProspectiveLongTrendExactHorizonComparisonError(
            "paired horizons use different execution configs"
        )

    five_index = _option_index(five)
    fifteen_index = _option_index(fifteen)
    exact_five = {
        key
        for key, row in five_index.items()
        if row.get("exact_realized_pnl") is not None
    }
    exact_fifteen = {
        key
        for key, row in fifteen_index.items()
        if row.get("exact_realized_pnl") is not None
    }
    paired_ids = exact_five & exact_fifteen
    five_source_ids = set(five_index)
    fifteen_source_ids = set(fifteen_index)
    common_source_ids = five_source_ids & fifteen_source_ids
    five_incomplete_reasons = _incomplete_reason_counts(five_index)
    fifteen_incomplete_reasons = _incomplete_reason_counts(
        fifteen_index
    )

    paired: list[dict[str, object]] = []
    for opportunity_id in paired_ids:
        five_row = five_index[opportunity_id]
        fifteen_row = fifteen_index[opportunity_id]
        for key in ("timestamp_ms", "market", "direction"):
            if five_row.get(key) != fifteen_row.get(key):
                raise ProspectiveLongTrendExactHorizonComparisonError(
                    f"paired horizon lineage mismatch: {key}"
                )
        five_pnl = _decimal(
            five_row["exact_realized_pnl"],
            "5m exact_realized_pnl",
        )
        fifteen_pnl = _decimal(
            fifteen_row["exact_realized_pnl"],
            "15m exact_realized_pnl",
        )
        five_return = _decimal(
            five_row["exact_realized_return_fraction"],
            "5m exact_realized_return_fraction",
        )
        fifteen_return = _decimal(
            fifteen_row["exact_realized_return_fraction"],
            "15m exact_realized_return_fraction",
        )
        paired.append(
            {
                "opportunity_id": opportunity_id,
                "timestamp_ms": five_row["timestamp_ms"],
                "market": five_row["market"],
                "direction": five_row["direction"],
                "five_minute_exact_realized_pnl": str(five_pnl),
                "fifteen_minute_exact_realized_pnl": str(fifteen_pnl),
                "pnl_delta_5m_minus_15m": str(five_pnl - fifteen_pnl),
                "five_minute_exact_return_fraction": str(five_return),
                "fifteen_minute_exact_return_fraction": str(
                    fifteen_return
                ),
                "return_fraction_delta_5m_minus_15m": str(
                    five_return - fifteen_return
                ),
            }
        )
    paired.sort(
        key=lambda row: (
            cast(int, row["timestamp_ms"]),
            cast(str, row["market"]),
            cast(str, row["opportunity_id"]),
        )
    )
    paired_rows = tuple(paired)
    deltas = tuple(
        _decimal(row["pnl_delta_5m_minus_15m"], "paired delta")
        for row in paired_rows
    )
    total_delta = sum(deltas, ZERO)
    return_deltas = tuple(
        _decimal(
            row["return_fraction_delta_5m_minus_15m"],
            "paired return-fraction delta",
        )
        for row in paired_rows
    )
    total_return_delta = sum(return_deltas, ZERO)
    total_five = sum(
        (
            _decimal(
                row["five_minute_exact_realized_pnl"],
                "5m paired pnl",
            )
            for row in paired_rows
        ),
        ZERO,
    )
    total_fifteen = sum(
        (
            _decimal(
                row["fifteen_minute_exact_realized_pnl"],
                "15m paired pnl",
            )
            for row in paired_rows
        ),
        ZERO,
    )
    markets = frozenset(
        cast(str, row["market"])
        for row in paired_rows
    )
    trade_loo = _leave_one_trade_totals(deltas)
    market_loo = _leave_one_market_totals(paired_rows)
    return_trade_loo = _leave_one_trade_totals(return_deltas)
    return_market_loo = _leave_one_market_totals(
        paired_rows,
        delta_key="return_fraction_delta_5m_minus_15m",
    )

    midpoint = len(deltas) // 2
    first_half = sum(deltas[:midpoint], ZERO)
    second_half = sum(deltas[midpoint:], ZERO)
    return_first_half = sum(return_deltas[:midpoint], ZERO)
    return_second_half = sum(return_deltas[midpoint:], ZERO)
    chronological_complete = midpoint > 0 and midpoint < len(deltas)

    minimum_sample_met = (
        len(deltas) >= MIN_PAIRED_OPTIONS
        and len(markets) >= MIN_MARKETS
    )
    five_robust = (
        minimum_sample_met
        and total_delta > ZERO
        and bool(trade_loo)
        and min(trade_loo) > ZERO
        and bool(market_loo)
        and min(market_loo) > ZERO
        and chronological_complete
        and first_half > ZERO
        and second_half > ZERO
    )
    fifteen_robust = (
        minimum_sample_met
        and total_delta < ZERO
        and bool(trade_loo)
        and max(trade_loo) < ZERO
        and bool(market_loo)
        and max(market_loo) < ZERO
        and chronological_complete
        and first_half < ZERO
        and second_half < ZERO
    )
    preferred_horizon = (
        "5m" if five_robust else "15m" if fifteen_robust else "none"
    )
    five_size_normalized_robust = (
        minimum_sample_met
        and total_return_delta > ZERO
        and bool(return_trade_loo)
        and min(return_trade_loo) > ZERO
        and bool(return_market_loo)
        and min(return_market_loo) > ZERO
        and chronological_complete
        and return_first_half > ZERO
        and return_second_half > ZERO
    )
    fifteen_size_normalized_robust = (
        minimum_sample_met
        and total_return_delta < ZERO
        and bool(return_trade_loo)
        and max(return_trade_loo) < ZERO
        and bool(return_market_loo)
        and max(return_market_loo) < ZERO
        and chronological_complete
        and return_first_half < ZERO
        and return_second_half < ZERO
    )
    size_normalized_preferred_horizon = (
        "5m"
        if five_size_normalized_robust
        else "15m"
        if fifteen_size_normalized_robust
        else "none"
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "common_started_at_ms": COMMON_FROZEN_STARTED_AT_MS,
        "five_minute_horizon_ms": FIVE_MINUTE_HORIZON_MS,
        "fifteen_minute_horizon_ms": FIFTEEN_MINUTE_HORIZON_MS,
        "execution_config_sha256": five["execution_config_sha256"],
        "five_minute_source_options": len(five_source_ids),
        "fifteen_minute_source_options": len(fifteen_source_ids),
        "common_source_options": len(common_source_ids),
        "five_minute_only_source_options": len(
            five_source_ids - fifteen_source_ids
        ),
        "fifteen_minute_only_source_options": len(
            fifteen_source_ids - five_source_ids
        ),
        "five_minute_incomplete_reasons": five_incomplete_reasons,
        "fifteen_minute_incomplete_reasons": (
            fifteen_incomplete_reasons
        ),
        "five_minute_exact_options": len(exact_five),
        "fifteen_minute_exact_options": len(exact_fifteen),
        "paired_exact_options": len(paired_rows),
        "five_minute_only_exact_options": len(exact_five - exact_fifteen),
        "fifteen_minute_only_exact_options": len(exact_fifteen - exact_five),
        "market_count": len(markets),
        "minimum_paired_options": MIN_PAIRED_OPTIONS,
        "minimum_markets": MIN_MARKETS,
        "minimum_sample_met": minimum_sample_met,
        "five_minute_total_pnl_on_paired": str(total_five),
        "fifteen_minute_total_pnl_on_paired": str(total_fifteen),
        "total_pnl_delta_5m_minus_15m": str(total_delta),
        "mean_pnl_delta_5m_minus_15m": (
            None
            if not deltas
            else str(total_delta / Decimal(len(deltas)))
        ),
        "total_return_fraction_delta_5m_minus_15m": str(
            total_return_delta
        ),
        "mean_return_fraction_delta_5m_minus_15m": (
            None
            if not return_deltas
            else str(
                total_return_delta / Decimal(len(return_deltas))
            )
        ),
        "five_minute_better_count": sum(value > ZERO for value in deltas),
        "fifteen_minute_better_count": sum(value < ZERO for value in deltas),
        "tie_count": sum(value == ZERO for value in deltas),
        "leave_one_trade_min_delta": (
            None if not trade_loo else str(min(trade_loo))
        ),
        "leave_one_trade_max_delta": (
            None if not trade_loo else str(max(trade_loo))
        ),
        "leave_one_market_min_delta": (
            None if not market_loo else str(min(market_loo))
        ),
        "leave_one_market_max_delta": (
            None if not market_loo else str(max(market_loo))
        ),
        "chronological_first_half_delta": str(first_half),
        "chronological_second_half_delta": str(second_half),
        "size_normalized_leave_one_trade_min_delta": (
            None
            if not return_trade_loo
            else str(min(return_trade_loo))
        ),
        "size_normalized_leave_one_trade_max_delta": (
            None
            if not return_trade_loo
            else str(max(return_trade_loo))
        ),
        "size_normalized_leave_one_market_min_delta": (
            None
            if not return_market_loo
            else str(min(return_market_loo))
        ),
        "size_normalized_leave_one_market_max_delta": (
            None
            if not return_market_loo
            else str(max(return_market_loo))
        ),
        "size_normalized_chronological_first_half_delta": str(
            return_first_half
        ),
        "size_normalized_chronological_second_half_delta": str(
            return_second_half
        ),
        "chronological_complete": chronological_complete,
        "five_minute_robustly_better": five_robust,
        "fifteen_minute_robustly_better": fifteen_robust,
        "preferred_horizon": preferred_horizon,
        "five_minute_size_normalized_robustly_better": (
            five_size_normalized_robust
        ),
        "fifteen_minute_size_normalized_robustly_better": (
            fifteen_size_normalized_robust
        ),
        "size_normalized_preferred_horizon": (
            size_normalized_preferred_horizon
        ),
        "paired_results": list(paired_rows),
    }
