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
) -> dict[str, object]:
    numeric = Decimal(value)
    direction = "long" if numeric > 0 else "short" if numeric < 0 else "no_trade"
    return {
        "decision_fact_id": f"fact-{timestamp_ms}-{value}",
        "strategy_decision_id": f"decision-{timestamp_ms}-{value}",
        "market": "HYPE",
        "decision_timestamp_ms": timestamp_ms,
        "feature_snapshot_id": f"feature-{timestamp_ms}",
        "feature_as_of_ms": timestamp_ms,
        "horizon_ms": 900_000,
        "target_as_of_ms": timestamp_ms + 900_000,
        "forward_mark_return": value,
        "favored_direction": direction,
        "reason_codes": [reason],
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
    )
    payload = report.to_dict()

    assert payload["chronological_holdout_required"] is True
    assert payload["material_move_only"] is True
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
    )

    assert report.to_dict()["execution_authority"] is False
