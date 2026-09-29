from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-replacement-5m-real-l2-exit-v1"
EXIT_HORIZON_MS: Final = 300_000
ZERO: Final = Decimal("0")


class ProspectiveReplacementExitPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveReplacementExitPolicyState:
    started_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID
    exit_horizon_ms: int = EXIT_HORIZON_MS

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported replacement-exit state schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported replacement-exit candidate")
        if self.exit_horizon_ms != EXIT_HORIZON_MS:
            raise ValueError("unsupported replacement-exit horizon")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "exit_horizon_ms": self.exit_horizon_ms,
                "entry_policy": "candidate_caused_replacement_fill",
                "exit_policy": "real_l2_reduce_only_ioc_at_fixed_horizon",
                "funding_policy": "exact_captured_hourly_boundaries",
                "cross_horizon_selection": "frozen_single_horizon",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveReplacementExitPolicyState:
        if not isinstance(raw, dict):
            raise ProspectiveReplacementExitPolicyError(
                "replacement-exit state must be an object"
            )
        expected_rule = {
            "exit_horizon_ms": EXIT_HORIZON_MS,
            "entry_policy": "candidate_caused_replacement_fill",
            "exit_policy": "real_l2_reduce_only_ioc_at_fixed_horizon",
            "funding_policy": "exact_captured_hourly_boundaries",
            "cross_horizon_selection": "frozen_single_horizon",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveReplacementExitPolicyError(
                "replacement-exit rule does not match frozen candidate"
            )
        schema = raw.get("schema_version")
        started = raw.get("started_at_ms")
        candidate = raw.get("candidate_id")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ProspectiveReplacementExitPolicyError(
                "schema_version must be an integer"
            )
        if isinstance(started, bool) or not isinstance(started, int):
            raise ProspectiveReplacementExitPolicyError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate, str):
            raise ProspectiveReplacementExitPolicyError(
                "candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started,
                schema_version=schema,
                candidate_id=candidate,
            )
        except ValueError as exc:
            raise ProspectiveReplacementExitPolicyError(str(exc)) from exc


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveReplacementExitPolicyError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveReplacementExitPolicyError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProspectiveReplacementExitPolicyError(
            f"{field} must be finite"
        )
    return resolved


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveReplacementExitPolicyError(
            f"{field} must be a non-empty string"
        )
    return value


def prospective_replacement_exit_policy_summary(
    realized_pnl: dict[str, object],
    state: ProspectiveReplacementExitPolicyState,
) -> dict[str, object]:
    if realized_pnl.get("funding_evidence_modeled") is not True:
        raise ProspectiveReplacementExitPolicyError(
            "exact funding evidence must be modeled"
        )
    if realized_pnl.get("cross_horizon_economics_aggregated") is not False:
        raise ProspectiveReplacementExitPolicyError(
            "replacement exit horizons must remain economically separate"
        )
    raw_horizons = realized_pnl.get("horizons_ms")
    if not isinstance(raw_horizons, list) or EXIT_HORIZON_MS not in raw_horizons:
        raise ProspectiveReplacementExitPolicyError(
            "frozen replacement exit horizon is unavailable"
        )
    raw_options = realized_pnl.get("option_results")
    if not isinstance(raw_options, list):
        raise ProspectiveReplacementExitPolicyError(
            "replacement realized-PnL option results are invalid"
        )

    discovery_options_excluded = 0
    prospective_options = 0
    exact_options = 0
    incomplete_options = 0
    wins = 0
    losses = 0
    breakeven = 0
    zero_boundary_exact = 0
    funded_exact = 0
    exact_pnl = ZERO
    incomplete_reasons: Counter[str] = Counter()
    by_market: Counter[str] = Counter()
    option_results: list[dict[str, object]] = []

    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            raise ProspectiveReplacementExitPolicyError(
                "replacement realized-PnL option is invalid"
            )
        option_id = _text(raw_option.get("option_id"), "option_id")
        opportunity_id = _text(
            raw_option.get("opportunity_id"),
            "opportunity_id",
        )
        opportunity_timestamp_ms = _integer(
            raw_option.get("opportunity_timestamp_ms"),
            "opportunity_timestamp_ms",
        )
        market = _text(
            raw_option.get("opportunity_market"),
            "opportunity_market",
        )
        if opportunity_timestamp_ms < state.started_at_ms:
            discovery_options_excluded += 1
            continue

        prospective_options += 1
        exits = raw_option.get("exits")
        if not isinstance(exits, dict):
            raise ProspectiveReplacementExitPolicyError(
                "replacement option exits are invalid"
            )
        raw_exit = exits.get(str(EXIT_HORIZON_MS))
        if not isinstance(raw_exit, dict):
            incomplete_options += 1
            incomplete_reasons["missing_exit_result"] += 1
            option_results.append(
                {
                    "option_id": option_id,
                    "opportunity_id": opportunity_id,
                    "opportunity_timestamp_ms": opportunity_timestamp_ms,
                    "opportunity_market": market,
                    "exact_realized_pnl": None,
                    "incomplete_reason": "missing_exit_result",
                }
            )
            continue

        raw_exact = raw_exit.get("exact_realized_pnl")
        reason = raw_exit.get("incomplete_reason")
        if raw_exact is None:
            incomplete_options += 1
            reason_text = (
                "unknown"
                if reason is None
                else _text(reason, "incomplete_reason")
            )
            incomplete_reasons[reason_text] += 1
            option_results.append(
                {
                    "option_id": option_id,
                    "opportunity_id": opportunity_id,
                    "opportunity_timestamp_ms": opportunity_timestamp_ms,
                    "opportunity_market": market,
                    "exact_realized_pnl": None,
                    "incomplete_reason": reason_text,
                }
            )
            continue

        pnl = _decimal(raw_exact, "exact_realized_pnl")
        complete_close = raw_exit.get("complete_close")
        if complete_close is not True:
            raise ProspectiveReplacementExitPolicyError(
                "exact replacement PnL requires a complete close"
            )
        boundary_count = _integer(
            raw_exit.get("funding_boundary_count"),
            "funding_boundary_count",
        )
        evidence_count = _integer(
            raw_exit.get("funding_evidence_count"),
            "funding_evidence_count",
        )
        if boundary_count != evidence_count:
            raise ProspectiveReplacementExitPolicyError(
                "exact replacement PnL has incomplete funding evidence"
            )

        exact_options += 1
        exact_pnl += pnl
        by_market[market] += 1
        if pnl > ZERO:
            wins += 1
        elif pnl < ZERO:
            losses += 1
        else:
            breakeven += 1
        if boundary_count == 0:
            zero_boundary_exact += 1
        else:
            funded_exact += 1
        option_results.append(
            {
                "option_id": option_id,
                "opportunity_id": opportunity_id,
                "opportunity_timestamp_ms": opportunity_timestamp_ms,
                "opportunity_market": market,
                "exact_realized_pnl": str(pnl),
                "incomplete_reason": None,
            }
        )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "exit_horizon_ms": state.exit_horizon_ms,
        "claim_scope": (
            "post_freeze_candidate_caused_replacement_5m_exact_realized_pnl"
        ),
        "discovery_cohort_reused_for_validation": False,
        "discovery_options_excluded": discovery_options_excluded,
        "cross_horizon_selection_frozen": True,
        "prospective_options": prospective_options,
        "exact_realized_pnl_options": exact_options,
        "incomplete_options": incomplete_options,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "exact_realized_pnl": str(exact_pnl),
        "mean_exact_realized_pnl": (
            None
            if exact_options == 0
            else str(exact_pnl / Decimal(exact_options))
        ),
        "zero_boundary_exact_options": zero_boundary_exact,
        "funded_exact_options": funded_exact,
        "incomplete_reason_counts": dict(
            sorted(incomplete_reasons.items())
        ),
        "exact_options_by_market": dict(sorted(by_market.items())),
        "option_results": sorted(
            option_results,
            key=lambda item: (
                _integer(
                    item.get("opportunity_timestamp_ms"),
                    "opportunity_timestamp_ms",
                ),
                _text(item.get("option_id"), "option_id"),
            ),
        ),
        "strategy_level_pnl_claimed": False,
        "portfolio_counterfactual_complete": False,
    }
