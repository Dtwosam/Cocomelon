from __future__ import annotations

from decimal import Decimal

from cocomelon.research.no_trade_context_stability import (
    build_no_trade_context_stability_report,
)


def _outcome(
    *,
    timestamp_ms: int,
    value: str,
    trend: str,
    volatility: str,
    reason: str = "no_primary_thesis",
    decision_stage: str = "strategy_abstained",
    market: str = "HYPE",
) -> dict[str, object]:
    numeric = Decimal(value)
    direction = "long" if numeric > 0 else "short" if numeric < 0 else "no_trade"
    return {
        "decision_fact_id": f"fact-{timestamp_ms}-{value}",
        "strategy_decision_id": f"decision-{timestamp_ms}-{value}",
        "market": market,
        "decision_timestamp_ms": timestamp_ms,
        "feature_snapshot_id": f"feature-{timestamp_ms}",
        "feature_as_of_ms": timestamp_ms,
        "horizon_ms": 900_000,
        "target_as_of_ms": timestamp_ms + 900_000,
        "forward_mark_return": value,
        "favored_direction": direction,
        "reason_codes": [reason],
        "decision_stage": decision_stage,
        "trend_regime": trend,
        "volatility_regime": volatility,
        "return_15m_sign": "positive" if trend == "up" else "negative",
        "return_1h_sign": "positive" if trend == "up" else "negative",
        "funding_sign": "positive",
        "book_imbalance_sign": "negative" if volatility == "high" else "positive",
    }


def _report(*, validation_flip: bool = False) -> dict[str, object]:
    outcomes: list[dict[str, object]] = []
    timestamp = 1_000_000

    for index in range(10):
        outcomes.append(
            _outcome(
                timestamp_ms=timestamp,
                value="0.02" if index < 8 else "-0.02",
                trend="up",
                volatility="high",
            )
        )
        timestamp += 1
    for index in range(10):
        outcomes.append(
            _outcome(
                timestamp_ms=timestamp,
                value="0.02" if index < 5 else "-0.02",
                trend="mixed",
                volatility="normal",
            )
        )
        timestamp += 1

    long_validation = 2 if validation_flip else 6
    for index in range(8):
        outcomes.append(
            _outcome(
                timestamp_ms=timestamp,
                value="0.02" if index < long_validation else "-0.02",
                trend="up",
                volatility="high",
            )
        )
        timestamp += 1
    for index in range(12):
        outcomes.append(
            _outcome(
                timestamp_ms=timestamp,
                value="0.02" if index < 4 else "-0.02",
                trend="mixed",
                volatility="normal",
            )
        )
        timestamp += 1

    return {
        "decision_state_digest": "a" * 64,
        "feature_state_digest": "b" * 64,
        "diagnostic_only": True,
        "hypothetical_pnl": False,
        "execution_authority": False,
        "outcomes": outcomes,
    }


def test_context_pattern_must_survive_chronological_holdout() -> None:
    report = build_no_trade_context_stability_report(
        _report(),
        split_fraction=Decimal("0.50"),
        material_thresholds_bps=(100,),
        min_discovery_rows=8,
        min_validation_rows=6,
        min_discovery_direction_share=Decimal("0.70"),
        min_validation_direction_share=Decimal("0.65"),
        min_validation_lift=Decimal("0.10"),
        validation_block_count=1,
        min_validation_block_rows=6,
        min_validation_block_direction_share=Decimal("0.65"),
        required_validation_blocks=1,
    )
    payload = report.to_dict()

    assert payload["chronological_holdout_required"] is True
    assert payload["material_move_only"] is True
    assert payload["directional_candidate_source"] == "strategy_abstained_only"
    assert payload["strategy_abstained_outcomes"] == 40
    assert payload["eligibility_blocked_outcomes"] == 0
    assert payload["promotion_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["validated_candidate_count"] >= 1

    analyses = payload["analyses"]
    assert isinstance(analyses, tuple)
    candidates = analyses[0]["candidates"]
    assert isinstance(candidates, tuple)
    target = next(
        item
        for item in candidates
        if item["dimensions"] == ("trend_regime", "volatility_regime")
        and item["values"] == ("up", "high")
    )
    assert target["dominant_direction"] == "long"
    assert target["discovery_direction_share"] == "0.8"
    assert target["validation_same_direction_share"] == "0.75"
    assert target["validation_baseline_direction_share"] == "0.5"
    assert target["validation_lift_vs_baseline"] == "0.25"
    assert target["stable_on_validation"] is True


def test_discovery_pattern_that_flips_later_is_not_stable() -> None:
    report = build_no_trade_context_stability_report(
        _report(validation_flip=True),
        split_fraction=Decimal("0.50"),
        material_thresholds_bps=(100,),
        min_discovery_rows=8,
        min_validation_rows=6,
        min_discovery_direction_share=Decimal("0.70"),
        min_validation_direction_share=Decimal("0.65"),
        min_validation_lift=Decimal("0.10"),
        validation_block_count=1,
        min_validation_block_rows=6,
        min_validation_block_direction_share=Decimal("0.65"),
        required_validation_blocks=1,
    )
    payload = report.to_dict()
    analyses = payload["analyses"]
    assert isinstance(analyses, tuple)
    candidates = analyses[0]["candidates"]
    assert isinstance(candidates, tuple)
    target = next(
        item
        for item in candidates
        if item["dimensions"] == ("trend_regime", "volatility_regime")
        and item["values"] == ("up", "high")
    )

    assert target["dominant_direction"] == "long"
    assert target["validation_same_direction_share"] == "0.25"
    assert target["stable_on_validation"] is False


def test_forward_source_must_remain_authority_negative() -> None:
    source = _report()
    source["execution_authority"] = True

    try:
        build_no_trade_context_stability_report(source)
    except RuntimeError as exc:
        assert "execution authority" in str(exc)
    else:
        raise AssertionError("authority-bearing source must fail closed")



def test_flat_forward_outcome_matches_no_trade_label() -> None:
    source = _report()
    source["outcomes"] = [
        _outcome(
            timestamp_ms=1_000,
            value="0",
            trend="mixed",
            volatility="normal",
        ),
        _outcome(
            timestamp_ms=2_000,
            value="0.02",
            trend="up",
            volatility="high",
        ),
    ]

    report = build_no_trade_context_stability_report(
        source,
        split_fraction=Decimal("0.50"),
        material_thresholds_bps=(100,),
        min_discovery_rows=1,
        min_validation_rows=1,
        min_discovery_direction_share=Decimal("0.51"),
        min_validation_direction_share=Decimal("0.51"),
        min_validation_lift=Decimal("0"),
        validation_block_count=1,
        min_validation_block_rows=1,
        min_validation_block_direction_share=Decimal("0.51"),
        required_validation_blocks=1,
    )

    assert report.to_dict()["execution_authority"] is False



def test_eligibility_blocked_outcomes_cannot_create_directional_candidates() -> None:
    source = _report()
    source["outcomes"] = [
        {
            **item,
            "decision_stage": "eligibility_blocked",
            "reason_codes": ["not_deep_ready"],
        }
        for item in source["outcomes"]
    ]

    report = build_no_trade_context_stability_report(
        source,
        split_fraction=Decimal("0.50"),
        material_thresholds_bps=(100,),
        min_discovery_rows=8,
        min_validation_rows=6,
        min_discovery_direction_share=Decimal("0.70"),
        min_validation_direction_share=Decimal("0.65"),
        min_validation_lift=Decimal("0.10"),
        validation_block_count=1,
        min_validation_block_rows=6,
        min_validation_block_direction_share=Decimal("0.65"),
        required_validation_blocks=1,
    )
    payload = report.to_dict()

    assert payload["source_outcome_count"] == 40
    assert payload["strategy_abstained_outcomes"] == 0
    assert payload["eligibility_blocked_outcomes"] == 40
    assert payload["validated_candidate_count"] == 0
    assert payload["analyses"] == ()


def test_mixed_source_discovers_only_from_strategy_abstentions() -> None:
    source = _report()
    blocked = [
        _outcome(
            timestamp_ms=2_000_000 + index,
            value="0.03",
            trend="up",
            volatility="high",
            reason="not_rankable",
            decision_stage="eligibility_blocked",
        )
        for index in range(40)
    ]
    source["outcomes"] = [*source["outcomes"], *blocked]

    report = build_no_trade_context_stability_report(
        source,
        split_fraction=Decimal("0.50"),
        material_thresholds_bps=(100,),
        min_discovery_rows=8,
        min_validation_rows=6,
        min_discovery_direction_share=Decimal("0.70"),
        min_validation_direction_share=Decimal("0.65"),
        min_validation_lift=Decimal("0.10"),
        validation_block_count=1,
        min_validation_block_rows=6,
        min_validation_block_direction_share=Decimal("0.65"),
        required_validation_blocks=1,
    )
    payload = report.to_dict()

    assert payload["source_outcome_count"] == 80
    assert payload["strategy_abstained_outcomes"] == 40
    assert payload["eligibility_blocked_outcomes"] == 40
    analyses = payload["analyses"]
    assert isinstance(analyses, tuple)
    assert analyses[0]["labeled_outcomes"] == 40



def _market_block_report(
    *,
    middle_block_short: int,
) -> dict[str, object]:
    outcomes: list[dict[str, object]] = []
    timestamp = 10_000_000

    for index in range(60):
        outcomes.append(
            _outcome(
                timestamp_ms=timestamp,
                value="-0.02" if index < 42 else "0.02",
                trend="mixed",
                volatility="normal",
                market="PONS",
            )
        )
        timestamp += 1

    block_short_counts = (7, middle_block_short, 7)
    for short_count in block_short_counts:
        for index in range(10):
            outcomes.append(
                _outcome(
                    timestamp_ms=timestamp,
                    value="-0.02" if index < short_count else "0.02",
                    trend="mixed",
                    volatility="normal",
                    market="PONS",
                )
            )
            timestamp += 1

    return {
        "decision_state_digest": "c" * 64,
        "feature_state_digest": "d" * 64,
        "diagnostic_only": True,
        "hypothetical_pnl": False,
        "execution_authority": False,
        "outcomes": outcomes,
    }


def test_market_candidate_must_survive_each_later_time_block() -> None:
    report = build_no_trade_context_stability_report(
        _market_block_report(middle_block_short=3),
        split_fraction=Decimal("0.6666666666666666666666666667"),
        material_thresholds_bps=(100,),
        min_discovery_rows=40,
        min_validation_rows=20,
        min_discovery_direction_share=Decimal("0.60"),
        min_validation_direction_share=Decimal("0.55"),
        min_validation_lift=Decimal("0"),
        validation_block_count=3,
        min_validation_block_rows=5,
        min_validation_block_direction_share=Decimal("0.51"),
        required_validation_blocks=3,
    )
    payload = report.to_dict()

    assert payload["market_aware"] is True
    assert payload["validation_block_consistency_required"] is True
    analyses = payload["analyses"]
    assert isinstance(analyses, tuple)
    market_candidate = next(
        item
        for item in analyses[0]["candidates"]
        if item["dimensions"] == ("market",)
        and item["values"] == ("PONS",)
    )
    assert market_candidate["validation_same_direction_share"] > "0.55"
    assert market_candidate["validation_block_outcomes"] == (10, 10, 10)
    assert market_candidate["validation_block_direction_shares"] == (
        "0.7",
        "0.3",
        "0.7",
    )
    assert market_candidate["stable_across_validation_blocks"] is False
    assert market_candidate["stable_on_validation"] is False


def test_market_candidate_can_survive_all_later_time_blocks() -> None:
    report = build_no_trade_context_stability_report(
        _market_block_report(middle_block_short=6),
        split_fraction=Decimal("0.6666666666666666666666666667"),
        material_thresholds_bps=(100,),
        min_discovery_rows=40,
        min_validation_rows=20,
        min_discovery_direction_share=Decimal("0.60"),
        min_validation_direction_share=Decimal("0.55"),
        min_validation_lift=Decimal("0"),
        validation_block_count=3,
        min_validation_block_rows=5,
        min_validation_block_direction_share=Decimal("0.51"),
        required_validation_blocks=3,
    )
    payload = report.to_dict()
    analyses = payload["analyses"]
    assert isinstance(analyses, tuple)
    market_candidate = next(
        item
        for item in analyses[0]["candidates"]
        if item["dimensions"] == ("market",)
        and item["values"] == ("PONS",)
    )

    assert market_candidate["validation_block_direction_shares"] == (
        "0.7",
        "0.6",
        "0.7",
    )
    assert market_candidate["validation_blocks_meeting_row_floor"] == 3
    assert market_candidate["validation_blocks_directionally_consistent"] == 3
    assert market_candidate["stable_across_validation_blocks"] is True
    assert market_candidate["stable_on_validation"] is True
