from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ResearchRiskMetrics:
    realized_closed_trade_max_drawdown_fraction: Decimal | None
    max_realized_planned_risk_utilization: Decimal | None


def _decimal(observation: dict[str, object], field: str) -> Decimal:
    value = observation.get(field)
    if not isinstance(value, str):
        raise ValueError(f"stored research observation {field} is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"stored research observation {field} is invalid") from exc
    if not result.is_finite():
        raise ValueError(f"stored research observation {field} is invalid")
    return result


def _integer(observation: dict[str, object], field: str) -> int:
    value = observation.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"stored research observation {field} is invalid")
    return value


def _string(observation: dict[str, object], field: str) -> str:
    value = observation.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"stored research observation {field} is invalid")
    return value


def compute_checkpoint_risk_metrics(
    observations: tuple[dict[str, object], ...],
) -> ResearchRiskMetrics:
    if not observations:
        return ResearchRiskMetrics(
            realized_closed_trade_max_drawdown_fraction=None,
            max_realized_planned_risk_utilization=None,
        )

    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (
                _integer(item, "closed_at_ms"),
                _string(item, "trade_id"),
            ),
        )
    )
    running = _decimal(ordered[0], "equity_before")
    if running <= ZERO:
        raise ValueError("research realized equity must remain positive")
    peak = running
    maximum_drawdown = ZERO
    maximum_planned_risk_utilization = ZERO

    with localcontext(AUTHORITATIVE_CONTEXT):
        for observation in ordered:
            running += _decimal(observation, "net_pnl")
            if running <= ZERO:
                raise ValueError("research realized equity must remain positive")
            if running > peak:
                peak = running
            else:
                drawdown = (peak - running) / peak
                if drawdown > maximum_drawdown:
                    maximum_drawdown = drawdown

            net_r = _decimal(observation, "net_r")
            realized_loss_to_planned_risk = max(ZERO, -net_r)
            if realized_loss_to_planned_risk > maximum_planned_risk_utilization:
                maximum_planned_risk_utilization = realized_loss_to_planned_risk

    return ResearchRiskMetrics(
        realized_closed_trade_max_drawdown_fraction=maximum_drawdown,
        max_realized_planned_risk_utilization=maximum_planned_risk_utilization,
    )
