from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
MIN_PROSPECTIVE_ADMISSIONS: Final = 40
MIN_MARKETS: Final = 4
STABILITY_BLOCKS: Final = 4


class MomentumPullbackFeeStressError(ValueError):
    """The research-only original prospective markout report is malformed."""


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise MomentumPullbackFeeStressError(f"{field} must be a nonnegative integer")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MomentumPullbackFeeStressError(f"{field} must be nonempty")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise MomentumPullbackFeeStressError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise MomentumPullbackFeeStressError(f"{field} is not a decimal") from exc
    if not parsed.is_finite():
        raise MomentumPullbackFeeStressError(f"{field} must be finite")
    return parsed


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _as_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _marked_fee_estimate(gross: Decimal, *, side: str, fee: Decimal) -> Decimal:
    # Both marketable legs are hypothetically executed EXACTLY at the
    # original mark. This ignores spread, slippage, missed orders, funding,
    # minimum-notional constraints and simultaneous portfolio occupancy.
    # The exit NOTIONAL changes with the return. Do not approximate both
    # fee legs as one identical notional and call the result genuine PnL.
    exit_notional_ratio = ONE + (gross if side == "long" else -gross)
    if exit_notional_ratio <= ZERO:
        raise MomentumPullbackFeeStressError(
            "directional markout implies nonpositive exit price"
        )
    return gross - fee * (ONE + exit_notional_ratio)


def _block_receipt(
    rows: Sequence[tuple[str, str, Decimal | None]],
) -> dict[str, object]:
    values = [net for _market, _side, net in rows if net is not None]
    mean_net = _mean(values)
    return {
        "opportunities": len(rows),
        "settled": len(values),
        "missing": len(rows) - len(values),
        "optimistic_fee_only_mean_net_return": _as_str(mean_net),
        "strictly_positive_complete_block": (
            bool(rows)
            and len(values) == len(rows)
            and mean_net is not None
            and mean_net > ZERO
        ),
    }


def audit_momentum_pullback_optimistic_fee_stability(
    summary: Mapping[str, object],
    *,
    config: PaperExecutionConfig | None = None,
) -> dict[str, object]:
    """Stress ALL frozen horizons, never promote a favorable markout.

    The old original v3 source failed its clock continuity gate. Even a
    positive output from this function is NOT a source-clean 72h trial,
    executable strategy or capital-matched account. Zero spread/slippage
    and missing funding favor the candidate, making a negative result a
    particularly strong rejection of this mark-to-mark research lead.
    """
    if (
        summary.get("research_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("descriptive_only") is not True
    ):
        raise MomentumPullbackFeeStressError(
            "original report must be explicitly research-only and nonpromotable"
        )
    if summary.get("integrity_clean") is not True:
        raise MomentumPullbackFeeStressError(
            "original report feature integrity is not clean"
        )
    candidate_id = _text(summary.get("candidate_id"), "candidate_id")
    started_ms = _integer(summary.get("started_at_ms"), "started_at_ms")
    if summary.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise MomentumPullbackFeeStressError(
            "original report changed the frozen forward horizons"
        )
    raw_rows = summary.get("rows")
    if not isinstance(raw_rows, list):
        raise MomentumPullbackFeeStressError("original rows must be a list")
    execution = config or PaperExecutionConfig()
    fee = execution.taker_fee_rate
    if not fee.is_finite() or fee < ZERO:
        raise MomentumPullbackFeeStressError("invalid taker fee schedule")

    selected: list[tuple[int, str, str, str, dict[str, Decimal | None]]] = []
    seen: set[tuple[int, str]] = set()
    previous_order: tuple[int, str, str] | None = None
    total_admitted = 0
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise MomentumPullbackFeeStressError("original row must be an object")
        timestamp = _integer(raw.get("timestamp_ms"), "timestamp_ms")
        if timestamp < started_ms:
            raise MomentumPullbackFeeStressError("row predates prospective freeze")
        market = _text(raw.get("market"), "market")
        opportunity_id = _text(raw.get("opportunity_id"), "opportunity_id")
        order_key = (timestamp, market, opportunity_id)
        if previous_order is not None and order_key < previous_order:
            raise MomentumPullbackFeeStressError("source row ordering changed")
        previous_order = order_key
        identity = (timestamp, opportunity_id)
        if identity in seen:
            raise MomentumPullbackFeeStressError("duplicate original opportunity")
        seen.add(identity)
        decision = raw.get("pullback_decision")
        if decision not in ("ADMIT", "BLOCK"):
            raise MomentumPullbackFeeStressError("invalid frozen decision")
        side = raw.get("direction")
        if side not in ("long", "short"):
            raise MomentumPullbackFeeStressError("invalid opportunity direction")
        markouts = raw.get("markouts")
        if not isinstance(markouts, dict) or set(markouts) != {
            str(h) for h in FORWARD_HORIZONS_MS
        }:
            raise MomentumPullbackFeeStressError("frozen markout horizons differ")
        if decision != "ADMIT":
            continue
        total_admitted += 1
        by_horizon: dict[str, Decimal | None] = {}
        for horizon in FORWARD_HORIZONS_MS:
            key = str(horizon)
            markout = markouts[key]
            if not isinstance(markout, dict):
                raise MomentumPullbackFeeStressError("invalid original markout")
            if markout.get("target_at_ms") != timestamp + horizon:
                raise MomentumPullbackFeeStressError("altered frozen target clock")
            status = markout.get("status")
            if status == "settled":
                gross = _decimal(
                    markout.get("directional_return"), "directional_return"
                )
                by_horizon[key] = _marked_fee_estimate(
                    gross, side=side, fee=fee
                )
            elif status in ("stale", "pending", "missing_path"):
                if markout.get("directional_return") is not None:
                    raise MomentumPullbackFeeStressError(
                        "unsettled markout cannot supply gross return"
                    )
                by_horizon[key] = None
            else:
                raise MomentumPullbackFeeStressError("unknown markout status")
        selected.append((timestamp, market, opportunity_id, side, by_horizon))

    if summary.get("pullback_admitted") != total_admitted:
        raise MomentumPullbackFeeStressError("admission count disagrees with rows")
    if summary.get("risk_approved_evaluated") != len(raw_rows):
        raise MomentumPullbackFeeStressError("evaluated row count disagrees")
    n = len(selected)
    horizon_receipts: dict[str, dict[str, object]] = {}
    for horizon in FORWARD_HORIZONS_MS:
        key = str(horizon)
        entries = [(market, side, values[key])
                   for _, market, _, side, values in selected]
        overall = _block_receipt(entries)
        chronological_blocks = [
            _block_receipt(entries[i * n // STABILITY_BLOCKS:
                                   (i + 1) * n // STABILITY_BLOCKS])
            for i in range(STABILITY_BLOCKS)
        ]
        markets = sorted({market for market, _, _ in entries})
        market_omissions = {
            market: _block_receipt([
                entry for entry in entries if entry[0] != market
            ])
            for market in markets
        }
        negative_market = [
            market for market, receipt in market_omissions.items()
            if receipt["strictly_positive_complete_block"] is not True
        ]
        closed_blocks_pass = all(
            block["strictly_positive_complete_block"] is True
            for block in chronological_blocks
        )
        sufficient = n >= MIN_PROSPECTIVE_ADMISSIONS and len(markets) >= MIN_MARKETS
        conditional_stress_pass = (
            sufficient
            and overall["strictly_positive_complete_block"] is True
            and closed_blocks_pass
            and not negative_market
        )
        horizon_receipts[key] = {
            "horizon_ms": horizon,
            "admitted": n,
            "market_count": len(markets),
            "optimistic_fee_only": overall,
            "chronological_blocks": chronological_blocks,
            "all_chronological_blocks_positive": closed_blocks_pass,
            "leave_one_market_out": market_omissions,
            "nonpositive_or_incomplete_market_omissions": negative_market,
            "minimum_admitted_required": MIN_PROSPECTIVE_ADMISSIONS,
            "sample_sufficient": sufficient,
            "conditional_mark_only_stress_pass": conditional_stress_pass,
            "eligible_for_strategy_promotion": False,
        }

    return {
        "schema": "momentum-pullback-original-markout-fee-stress-v1",
        "candidate_id": candidate_id,
        "prospective_started_at_ms": started_ms,
        "fee_schedule_id": execution.fee_schedule_id,
        "taker_fee_per_side": str(fee),
        "observed_original_admissions": n,
        "horizons": horizon_receipts,
        "scope": (
            "optimistic_exact_mark_entry_exit_fee_estimate_only;"
            "no_spread_slippage_funding_order_misses_portfolio_occupancy"
        ),
        "all_original_source_continuity_verified": False,
        "funding_and_executable_book_costs_verified": False,
        "independent_capital_matched_paper_verified": False,
        "positive_absolute_after_cost_equity_verified": False,
        "promotion_authority": False,
        "execution_authority": False,
        "live_orders": False,
    }
