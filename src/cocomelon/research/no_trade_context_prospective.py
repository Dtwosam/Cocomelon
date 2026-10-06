from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast
import json

from cocomelon.domain.strategy import Direction
from cocomelon.research.no_trade_context_candidate import (
    NoTradeContextCandidateFreeze,
    verify_no_trade_context_candidate_freeze,
)

ZERO = Decimal("0")
BPS = Decimal("10000")
NO_TRADE_CONTEXT_PROSPECTIVE_SCHEMA_VERSION = 1


class NoTradeContextProspectiveError(RuntimeError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise NoTradeContextProspectiveError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise NoTradeContextProspectiveError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise NoTradeContextProspectiveError(f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NoTradeContextProspectiveError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise NoTradeContextProspectiveError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise NoTradeContextProspectiveError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise NoTradeContextProspectiveError(f"{field} must be finite")
    return result


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _matches_context(
    raw: dict[str, object],
    freeze: NoTradeContextCandidateFreeze,
) -> bool:
    reasons = tuple(
        _string(item, "reason code")
        for item in _sequence(raw.get("reason_codes"), "reason_codes")
    )
    for dimension, expected in zip(
        freeze.dimensions,
        freeze.values,
        strict=True,
    ):
        if dimension == "reason_code":
            if expected not in reasons:
                return False
            continue
        if _string(raw.get(dimension), dimension) != expected:
            return False
    return True


@dataclass(frozen=True, slots=True)
class NoTradeContextProspectiveReport:
    candidate_id: str
    current_decision_state_digest: str
    current_feature_state_digest: str
    as_of_ms: int
    prospective_not_before_ms: int
    horizon_ms: int
    threshold_bps: int
    direction: Direction
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    matching_outcomes: int
    material_outcomes: int
    same_direction_material_outcomes: int
    opposite_direction_material_outcomes: int
    material_same_direction_share: Decimal | None
    mean_forward_mark_return: Decimal | None
    mean_directional_markout_return: Decimal | None
    mean_material_directional_markout_return: Decimal | None
    first_matching_decision_ms: int | None
    last_matching_decision_ms: int | None
    observation_span_ms: int
    schema_version: int = NO_TRADE_CONTEXT_PROSPECTIVE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "current_decision_state_digest": self.current_decision_state_digest,
            "current_feature_state_digest": self.current_feature_state_digest,
            "as_of_ms": self.as_of_ms,
            "prospective_not_before_ms": self.prospective_not_before_ms,
            "prospective_label_window_open": (
                self.as_of_ms
                >= self.prospective_not_before_ms + self.horizon_ms
            ),
            "horizon_ms": self.horizon_ms,
            "threshold_bps": self.threshold_bps,
            "direction": self.direction.value,
            "dimensions": self.dimensions,
            "values": self.values,
            "matching_outcomes": self.matching_outcomes,
            "material_outcomes": self.material_outcomes,
            "same_direction_material_outcomes": (
                self.same_direction_material_outcomes
            ),
            "opposite_direction_material_outcomes": (
                self.opposite_direction_material_outcomes
            ),
            "material_same_direction_share": (
                None
                if self.material_same_direction_share is None
                else str(self.material_same_direction_share)
            ),
            "mean_forward_mark_return": (
                None
                if self.mean_forward_mark_return is None
                else str(self.mean_forward_mark_return)
            ),
            "mean_directional_markout_return": (
                None
                if self.mean_directional_markout_return is None
                else str(self.mean_directional_markout_return)
            ),
            "mean_material_directional_markout_return": (
                None
                if self.mean_material_directional_markout_return is None
                else str(self.mean_material_directional_markout_return)
            ),
            "first_matching_decision_ms": self.first_matching_decision_ms,
            "last_matching_decision_ms": self.last_matching_decision_ms,
            "observation_span_ms": self.observation_span_ms,
            "prospective_only": True,
            "paper_only": True,
            "research_only": True,
            "diagnostic_only": True,
            "hypothetical_pnl": False,
            "cost_complete": False,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def build_no_trade_context_prospective_report(
    forward_report: dict[str, object],
    freeze: NoTradeContextCandidateFreeze,
) -> NoTradeContextProspectiveReport:
    if forward_report.get("diagnostic_only") is not True:
        raise NoTradeContextProspectiveError(
            "source forward report must be diagnostic-only"
        )
    if forward_report.get("hypothetical_pnl") is not False:
        raise NoTradeContextProspectiveError(
            "source forward report must not claim hypothetical PnL"
        )
    if forward_report.get("execution_authority") is not False:
        raise NoTradeContextProspectiveError(
            "source forward report must have no execution authority"
        )
    if _integer(
        forward_report.get("schema_version"),
        "schema_version",
    ) != 2:
        raise NoTradeContextProspectiveError(
            "source forward report schema is unsupported"
        )

    as_of_ms = _integer(forward_report.get("as_of_ms"), "as_of_ms")
    if as_of_ms < freeze.source_forward_as_of_ms:
        raise NoTradeContextProspectiveError(
            "prospective source predates candidate selection evidence"
        )
    decision_digest = _string(
        forward_report.get("decision_state_digest"),
        "decision_state_digest",
    )
    feature_digest = _string(
        forward_report.get("feature_state_digest"),
        "feature_state_digest",
    )

    matches: list[tuple[int, Decimal]] = []
    for raw_value in _sequence(forward_report.get("outcomes"), "outcomes"):
        raw = _mapping(raw_value, "outcome")
        if _integer(raw.get("horizon_ms"), "horizon_ms") != freeze.horizon_ms:
            continue
        if _string(raw.get("decision_stage"), "decision_stage") != (
            "strategy_abstained"
        ):
            continue
        decision_ms = _integer(
            raw.get("decision_timestamp_ms"),
            "decision_timestamp_ms",
        )
        if decision_ms < freeze.prospective_not_before_ms:
            continue
        if not _matches_context(raw, freeze):
            continue
        matches.append(
            (
                decision_ms,
                _decimal(
                    raw.get("forward_mark_return"),
                    "forward_mark_return",
                ),
            )
        )

    ordered = tuple(sorted(matches, key=lambda item: (item[0], item[1])))
    returns = tuple(value for _, value in ordered)
    threshold = Decimal(freeze.threshold_bps) / BPS
    material = tuple(value for value in returns if abs(value) >= threshold)
    aligned = tuple(
        value if freeze.direction is Direction.LONG else -value
        for value in returns
    )
    material_aligned = tuple(
        value if freeze.direction is Direction.LONG else -value
        for value in material
    )
    same = sum(value > ZERO for value in material_aligned)
    opposite = sum(value < ZERO for value in material_aligned)
    share = (
        Decimal(same) / Decimal(len(material))
        if material
        else None
    )
    first = ordered[0][0] if ordered else None
    last = ordered[-1][0] if ordered else None
    span = 0 if first is None or last is None else last - first

    return NoTradeContextProspectiveReport(
        candidate_id=freeze.candidate_id,
        current_decision_state_digest=decision_digest,
        current_feature_state_digest=feature_digest,
        as_of_ms=as_of_ms,
        prospective_not_before_ms=freeze.prospective_not_before_ms,
        horizon_ms=freeze.horizon_ms,
        threshold_bps=freeze.threshold_bps,
        direction=freeze.direction,
        dimensions=freeze.dimensions,
        values=freeze.values,
        matching_outcomes=len(returns),
        material_outcomes=len(material),
        same_direction_material_outcomes=same,
        opposite_direction_material_outcomes=opposite,
        material_same_direction_share=share,
        mean_forward_mark_return=_mean(returns),
        mean_directional_markout_return=_mean(aligned),
        mean_material_directional_markout_return=_mean(material_aligned),
        first_matching_decision_ms=first,
        last_matching_decision_ms=last,
        observation_span_ms=span,
    )


def load_and_score_no_trade_context_candidate(
    *,
    forward_report_path: Path,
    freeze_path: Path,
    selection_record_path: Path,
) -> NoTradeContextProspectiveReport:
    try:
        raw = json.loads(forward_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NoTradeContextProspectiveError(
            "forward report is invalid"
        ) from exc
    forward_report = _mapping(raw, "forward report")
    freeze = verify_no_trade_context_candidate_freeze(
        freeze_path,
        selection_record_path=selection_record_path,
    )
    return build_no_trade_context_prospective_report(
        forward_report,
        freeze,
    )
