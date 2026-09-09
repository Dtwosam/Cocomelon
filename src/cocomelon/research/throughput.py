from __future__ import annotations

from collections import Counter

from cocomelon.domain.strategy import Direction
from cocomelon.research.strategy_seam import (
    CandidateStrategyDecisionArtifact,
    strategy_decision_from_payload,
)

_DIRECTION_KEYS = (
    Direction.LONG.value,
    Direction.NO_TRADE.value,
    Direction.SHORT.value,
)


def _direction_payload(counts: Counter[str]) -> dict[str, int]:
    return {direction: counts[direction] for direction in _DIRECTION_KEYS}


def _reason_payload(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted(counts.items()))





def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"research decision throughput {field} must be a non-negative integer")
    return value


def _direction_counts(value: object, field: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != set(_DIRECTION_KEYS):
        raise ValueError(
            f"research decision throughput {field} must contain exact direction counts"
        )
    return {
        direction: _non_negative_int(value[direction], f"{field}.{direction}")
        for direction in _DIRECTION_KEYS
    }


def _reason_counts(value: object, field: str) -> dict[str, int]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key.strip() for key in value
    ):
        raise ValueError(f"research decision throughput {field} must be an object")
    result: dict[str, int] = {}
    for reason, raw_count in value.items():
        count = _non_negative_int(raw_count, f"{field}.{reason}")
        if count == 0:
            raise ValueError(
                f"research decision throughput {field}.{reason} must be positive"
            )
        result[reason] = count
    return dict(sorted(result.items()))


def normalize_decision_throughput_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("research decision throughput must be an object")

    required = {
        "decision_count",
        "direction_counts",
        "entry_eligible_decision_count",
        "entry_eligible_direction_counts",
        "entry_eligible_reason_counts",
        "entry_eligible_signal_count",
        "new_exposure_cutoff_ms",
        "post_cutoff_decision_count",
        "post_cutoff_direction_counts",
        "post_cutoff_reason_counts",
        "post_cutoff_signal_count",
        "reason_counts",
        "signal_count",
    }
    if set(value) != required:
        raise ValueError("research decision throughput fields are invalid")

    directions = _direction_counts(value["direction_counts"], "direction_counts")
    eligible_directions = _direction_counts(
        value["entry_eligible_direction_counts"],
        "entry_eligible_direction_counts",
    )
    post_cutoff_directions = _direction_counts(
        value["post_cutoff_direction_counts"],
        "post_cutoff_direction_counts",
    )
    decision_count = _non_negative_int(value["decision_count"], "decision_count")
    eligible_decision_count = _non_negative_int(
        value["entry_eligible_decision_count"],
        "entry_eligible_decision_count",
    )
    post_cutoff_decision_count = _non_negative_int(
        value["post_cutoff_decision_count"],
        "post_cutoff_decision_count",
    )
    signal_count = _non_negative_int(value["signal_count"], "signal_count")
    eligible_signal_count = _non_negative_int(
        value["entry_eligible_signal_count"],
        "entry_eligible_signal_count",
    )
    post_cutoff_signal_count = _non_negative_int(
        value["post_cutoff_signal_count"],
        "post_cutoff_signal_count",
    )
    cutoff_ms = _non_negative_int(
        value["new_exposure_cutoff_ms"],
        "new_exposure_cutoff_ms",
    )
    reasons = _reason_counts(value["reason_counts"], "reason_counts")
    eligible_reasons = _reason_counts(
        value["entry_eligible_reason_counts"],
        "entry_eligible_reason_counts",
    )
    post_cutoff_reasons = _reason_counts(
        value["post_cutoff_reason_counts"],
        "post_cutoff_reason_counts",
    )

    if sum(directions.values()) != decision_count:
        raise ValueError("research decision throughput direction counts do not match decisions")
    if sum(eligible_directions.values()) != eligible_decision_count:
        raise ValueError(
            "research decision throughput entry-eligible counts do not match decisions"
        )
    if sum(post_cutoff_directions.values()) != post_cutoff_decision_count:
        raise ValueError(
            "research decision throughput post-cutoff counts do not match decisions"
        )
    if eligible_decision_count + post_cutoff_decision_count != decision_count:
        raise ValueError("research decision throughput decision partition is inconsistent")
    for direction in _DIRECTION_KEYS:
        if (
            eligible_directions[direction] + post_cutoff_directions[direction]
            != directions[direction]
        ):
            raise ValueError(
                "research decision throughput direction partition is inconsistent"
            )

    expected_signal_count = directions[Direction.LONG.value] + directions[Direction.SHORT.value]
    expected_eligible_signals = (
        eligible_directions[Direction.LONG.value]
        + eligible_directions[Direction.SHORT.value]
    )
    expected_post_cutoff_signals = (
        post_cutoff_directions[Direction.LONG.value]
        + post_cutoff_directions[Direction.SHORT.value]
    )
    if signal_count != expected_signal_count:
        raise ValueError("research decision throughput signal count is inconsistent")
    if eligible_signal_count != expected_eligible_signals:
        raise ValueError(
            "research decision throughput entry-eligible signal count is inconsistent"
        )
    if post_cutoff_signal_count != expected_post_cutoff_signals:
        raise ValueError(
            "research decision throughput post-cutoff signal count is inconsistent"
        )

    combined_reasons = Counter(eligible_reasons)
    combined_reasons.update(post_cutoff_reasons)
    if dict(sorted(combined_reasons.items())) != reasons:
        raise ValueError("research decision throughput reason partition is inconsistent")

    return {
        "decision_count": decision_count,
        "direction_counts": directions,
        "entry_eligible_decision_count": eligible_decision_count,
        "entry_eligible_direction_counts": eligible_directions,
        "entry_eligible_reason_counts": eligible_reasons,
        "entry_eligible_signal_count": eligible_signal_count,
        "new_exposure_cutoff_ms": cutoff_ms,
        "post_cutoff_decision_count": post_cutoff_decision_count,
        "post_cutoff_direction_counts": post_cutoff_directions,
        "post_cutoff_reason_counts": post_cutoff_reasons,
        "post_cutoff_signal_count": post_cutoff_signal_count,
        "reason_counts": reasons,
        "signal_count": signal_count,
    }


def decision_throughput_payload(
    artifact: CandidateStrategyDecisionArtifact,
    *,
    new_exposure_cutoff_ms: int,
) -> dict[str, object]:
    if new_exposure_cutoff_ms < 0:
        raise ValueError("research new exposure cutoff must be non-negative")

    direction_counts: Counter[str] = Counter()
    eligible_direction_counts: Counter[str] = Counter()
    post_cutoff_direction_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    eligible_reason_counts: Counter[str] = Counter()
    post_cutoff_reason_counts: Counter[str] = Counter()

    for index, item in enumerate(artifact.decisions):
        if not isinstance(item, dict):
            raise ValueError(f"research candidate decision[{index}] must be an object")
        evaluated_at_ms = item.get("evaluated_at_ms")
        if (
            isinstance(evaluated_at_ms, bool)
            or not isinstance(evaluated_at_ms, int)
            or evaluated_at_ms < 0
        ):
            raise ValueError(
                f"research candidate decision[{index}] evaluated_at_ms must be non-negative"
            )
        decision = strategy_decision_from_payload(item.get("decision"))
        direction = decision.direction.value
        direction_counts[direction] += 1
        reason_counts.update(decision.reason_codes)

        if evaluated_at_ms < new_exposure_cutoff_ms:
            eligible_direction_counts[direction] += 1
            eligible_reason_counts.update(decision.reason_codes)
        else:
            post_cutoff_direction_counts[direction] += 1
            post_cutoff_reason_counts.update(decision.reason_codes)

    directions = _direction_payload(direction_counts)
    eligible_directions = _direction_payload(eligible_direction_counts)
    post_cutoff_directions = _direction_payload(post_cutoff_direction_counts)
    signal_count = directions[Direction.LONG.value] + directions[Direction.SHORT.value]
    eligible_signal_count = (
        eligible_directions[Direction.LONG.value]
        + eligible_directions[Direction.SHORT.value]
    )
    post_cutoff_signal_count = (
        post_cutoff_directions[Direction.LONG.value]
        + post_cutoff_directions[Direction.SHORT.value]
    )

    return normalize_decision_throughput_payload(
        {
            "decision_count": len(artifact.decisions),
            "direction_counts": directions,
            "entry_eligible_decision_count": sum(eligible_directions.values()),
            "entry_eligible_direction_counts": eligible_directions,
            "entry_eligible_reason_counts": _reason_payload(eligible_reason_counts),
            "entry_eligible_signal_count": eligible_signal_count,
            "new_exposure_cutoff_ms": new_exposure_cutoff_ms,
            "post_cutoff_decision_count": sum(post_cutoff_directions.values()),
            "post_cutoff_direction_counts": post_cutoff_directions,
            "post_cutoff_reason_counts": _reason_payload(post_cutoff_reason_counts),
            "post_cutoff_signal_count": post_cutoff_signal_count,
            "reason_counts": _reason_payload(reason_counts),
            "signal_count": signal_count,
        }
    )
