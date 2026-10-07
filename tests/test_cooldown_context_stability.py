from __future__ import annotations

from decimal import Decimal

from cocomelon.research.cooldown_context_stability import (
    build_cooldown_context_stability_report,
)


def _option(
    *,
    timestamp_ms: int,
    market: str,
    direction: str = "short",
    strategy: str = "trend",
    bucket: str = "15-30m",
    rank: int = 5,
    pnl_1h: str = "10",
    return_1h: str = "0.01",
) -> dict[str, object]:
    return {
        "opportunity_id": f"{market}-{timestamp_ms}-{strategy}-{direction}",
        "timestamp_ms": timestamp_ms,
        "market": market,
        "direction": direction,
        "lead_strategy": strategy,
        "rank_ordinal": rank,
        "elapsed_bucket": bucket,
        "markouts": {
            "3600000": {
                "status": "settled",
                "entry_fee_adjusted_mark_to_market_pnl": pnl_1h,
                "directional_return_fraction": return_1h,
            }
        },
    }


def _summary(options: list[dict[str, object]]) -> dict[str, object]:
    return {
        "candidate_id": (
            "prospective-consecutive-loss-cooldown-relaxation-v1"
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "forward_markout_only": True,
        "realized_pnl_modeled": False,
        "option_results": options,
    }


def test_direction_alone_can_never_become_a_candidate() -> None:
    report = build_cooldown_context_stability_report(
        _summary(
            [
                _option(
                    timestamp_ms=1_000 + index,
                    market=f"M{index % 4}",
                )
                for index in range(20)
            ]
        )
    )
    payload = report.to_dict()

    assert payload["direction_only_candidates_allowed"] is False
    assert payload["lead_strategy_context_required"] is True
    assert ("direction",) not in payload["candidate_dimension_sets"]
    assert all(
        "lead_strategy" in item["dimensions"]
        for item in payload["candidates"]
    )


def test_context_can_survive_holdout_and_robustness_gates() -> None:
    options: list[dict[str, object]] = []
    for index in range(20):
        options.append(
            _option(
                timestamp_ms=1_000 + index,
                market=("A", "B", "C", "D")[index % 4],
                strategy="trend",
                direction="short",
                bucket="15-30m",
                pnl_1h="10",
                return_1h="0.01",
            )
        )

    report = build_cooldown_context_stability_report(_summary(options))
    stable = tuple(
        item
        for item in report.candidates
        if item.stable_on_validation
    )

    assert stable
    trend = next(
        item
        for item in stable
        if item.dimensions == ("lead_strategy",)
        and item.values == ("trend",)
    )
    assert trend.discovery_rows == 12
    assert trend.validation_rows == 8
    assert trend.validation_markets == 4
    assert trend.validation_positive_share == Decimal("1")
    assert trend.validation_total_pnl == Decimal("80")
    assert trend.validation_leave_one_option_min_pnl == Decimal("70")
    assert trend.validation_leave_one_market_min_pnl == Decimal("60")
    assert trend.validation_block_rows == (4, 4)
    assert trend.validation_blocks_consistent == 2


def test_one_market_carrying_validation_fails_robustness() -> None:
    options: list[dict[str, object]] = []
    for index in range(12):
        options.append(
            _option(
                timestamp_ms=1_000 + index,
                market=("A", "B", "C", "D")[index % 4],
                pnl_1h="5",
                return_1h="0.01",
            )
        )
    validation = (
        ("A", "40"),
        ("A", "40"),
        ("A", "40"),
        ("A", "40"),
        ("B", "-10"),
        ("B", "-10"),
        ("C", "-10"),
        ("D", "-10"),
    )
    for index, (market, pnl) in enumerate(validation, start=12):
        options.append(
            _option(
                timestamp_ms=1_000 + index,
                market=market,
                pnl_1h=pnl,
                return_1h="0.01" if Decimal(pnl) > 0 else "-0.01",
            )
        )

    report = build_cooldown_context_stability_report(_summary(options))
    trend = next(
        item
        for item in report.candidates
        if item.dimensions == ("lead_strategy",)
        and item.values == ("trend",)
    )

    assert trend.validation_total_pnl == Decimal("120")
    assert trend.validation_leave_one_market_min_pnl == Decimal("-40")
    assert trend.stable_on_validation is False


def test_late_block_flip_fails_even_when_total_is_positive() -> None:
    options: list[dict[str, object]] = []
    for index in range(12):
        options.append(
            _option(
                timestamp_ms=1_000 + index,
                market=("A", "B", "C", "D")[index % 4],
                pnl_1h="5",
                return_1h="0.01",
            )
        )
    for index in range(4):
        options.append(
            _option(
                timestamp_ms=2_000 + index,
                market=("A", "B", "C", "D")[index],
                pnl_1h="20",
                return_1h="0.02",
            )
        )
    for index in range(4):
        options.append(
            _option(
                timestamp_ms=3_000 + index,
                market=("A", "B", "C", "D")[index],
                pnl_1h="-5",
                return_1h="-0.01",
            )
        )

    report = build_cooldown_context_stability_report(_summary(options))
    trend = next(
        item
        for item in report.candidates
        if item.dimensions == ("lead_strategy",)
        and item.values == ("trend",)
    )

    assert trend.validation_total_pnl == Decimal("60")
    assert trend.validation_block_pnl == (
        Decimal("80"),
        Decimal("-20"),
    )
    assert trend.validation_blocks_consistent == 1
    assert trend.stable_on_validation is False


def test_authority_drift_is_rejected() -> None:
    summary = _summary([])
    summary["execution_authority"] = True

    try:
        build_cooldown_context_stability_report(summary)
    except RuntimeError as exc:
        assert "authority or claim scope drift" in str(exc)
    else:
        raise AssertionError("authority drift must be rejected")
