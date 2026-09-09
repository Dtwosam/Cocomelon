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

    return {
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
