from __future__ import annotations

from decimal import Decimal
from typing import cast

from cocomelon.research.cadence_opportunity_learning import DEFAULT_CONFIG
from cocomelon.research.prospective_comparison_ledger import (
    validate_comparison_ledger,
)
from cocomelon.research.prospective_prediction_ledger import (
    validate_prediction_ledger,
)
from cocomelon.research.prospective_side_conditioned_delay import (
    CANDIDATE_ID as TIMING_CANDIDATE_ID,
    MIN_LONG_TRADES,
    MIN_PAIRED_EVALUABLE_TRADES,
    MIN_PROSPECTIVE_CLOSED_TRADES,
    MIN_SHORT_TRADES,
)
from cocomelon.research.prospective_timing_ledger import (
    validate_timing_ledger,
)

ZERO = Decimal("0")


class ProspectiveTradeQualityReadinessError(RuntimeError):
    pass


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveTradeQualityReadinessError(
            f"{key} must be an integer"
        )
    return value


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ProspectiveTradeQualityReadinessError(
            f"{key} must be a non-empty string"
        )
    return value


def _decimal(raw: object, *, field: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (ValueError, ArithmeticError) as exc:
        raise ProspectiveTradeQualityReadinessError(
            f"{field} must be a decimal"
        ) from exc
    if not value.is_finite():
        raise ProspectiveTradeQualityReadinessError(
            f"{field} must be finite"
        )
    return value


def _cadence_identity(row: dict[str, object]) -> tuple[int, str, str, str]:
    return (
        cast(int, row["boundary_ms"]),
        cast(str, row["market"]),
        cast(str, row["direction"]),
        cast(str, row["decision_id"]),
    )


def _validate_cross_ledger_alignment(
    prediction: dict[str, object],
    comparison: dict[str, object],
) -> tuple[dict[str, object], ...]:
    metadata_pairs = (
        ("model_family", "microstructure_model_family"),
        ("prospective_start_ms", "prospective_start_ms"),
        ("cadence_ms", "cadence_ms"),
        ("horizon_ms", "horizon_ms"),
        ("frozen_training_rows", "frozen_training_rows"),
        (
            "frozen_training_rows_sha256",
            "frozen_training_rows_sha256",
        ),
    )
    for prediction_key, comparison_key in metadata_pairs:
        if prediction.get(prediction_key) != comparison.get(comparison_key):
            raise ProspectiveTradeQualityReadinessError(
                "cadence ledger metadata mismatch: "
                f"{prediction_key}/{comparison_key}"
            )

    prediction_rows = cast(
        tuple[dict[str, object], ...],
        prediction["rows"],
    )
    comparison_rows = cast(
        tuple[dict[str, object], ...],
        comparison["rows"],
    )
    if _required_int(prediction, "row_count") != len(prediction_rows):
        raise ProspectiveTradeQualityReadinessError(
            "prediction row_count does not match rows"
        )
    if _required_int(comparison, "row_count") != len(comparison_rows):
        raise ProspectiveTradeQualityReadinessError(
            "comparison row_count does not match rows"
        )
    if _required_int(comparison, "prospective_rows") != len(
        comparison_rows
    ):
        raise ProspectiveTradeQualityReadinessError(
            "comparison prospective_rows does not match rows"
        )
    if len(prediction_rows) != len(comparison_rows):
        raise ProspectiveTradeQualityReadinessError(
            "cadence ledgers have different row counts"
        )

    prediction_by_identity = {
        _cadence_identity(row): row for row in prediction_rows
    }
    comparison_by_identity = {
        _cadence_identity(row): row for row in comparison_rows
    }
    if set(prediction_by_identity) != set(comparison_by_identity):
        raise ProspectiveTradeQualityReadinessError(
            "cadence ledger row identities differ"
        )

    for identity in sorted(prediction_by_identity):
        pred = prediction_by_identity[identity]
        paired = comparison_by_identity[identity]
        field_pairs = (
            ("decision_id", "decision_id"),
            ("boundary_ms", "boundary_ms"),
            ("market", "market"),
            ("direction", "direction"),
            ("realized_net_return", "realized_net_return"),
            (
                "prediction_net_return",
                "microstructure_prediction_net_return",
            ),
            ("admitted", "microstructure_admitted"),
        )
        for prediction_key, comparison_key in field_pairs:
            if pred.get(prediction_key) != paired.get(comparison_key):
                raise ProspectiveTradeQualityReadinessError(
                    "cadence ledger row mismatch: "
                    f"{prediction_key}/{comparison_key}"
                )
    return prediction_rows


def _cadence_blocks(
    rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    blocks: list[dict[str, object]] = []
    config = DEFAULT_CONFIG
    for index in range(config.stability_blocks):
        start = index * len(rows) // config.stability_blocks
        end = (index + 1) * len(rows) // config.stability_blocks
        block = rows[start:end]
        admitted = tuple(
            row for row in block if row["admitted"] is True
        )
        total = sum(
            (
                _decimal(
                    row["realized_net_return"],
                    field="realized_net_return",
                )
                for row in admitted
            ),
            ZERO,
        )
        mean = None if not admitted else total / Decimal(len(admitted))
        passes = (
            len(admitted) >= config.min_block_admitted
            and mean is not None
            and mean > ZERO
        )
        blocks.append(
            {
                "block_index": index,
                "prospective_rows": len(block),
                "admitted_rows": len(admitted),
                "candidate_net_return_sum": str(total),
                "candidate_mean_net_return": (
                    None if mean is None else str(mean)
                ),
                "passes": passes,
            }
        )
    return tuple(blocks)


def _cadence_readiness(
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    config = DEFAULT_CONFIG
    admitted = tuple(row for row in rows if row["admitted"] is True)
    long_rows = tuple(row for row in rows if row["direction"] == "long")
    short_rows = tuple(
        row for row in rows if row["direction"] == "short"
    )
    long_admitted = tuple(
        row for row in long_rows if row["admitted"] is True
    )
    short_admitted = tuple(
        row for row in short_rows if row["admitted"] is True
    )
    candidate_sum = sum(
        (
            _decimal(
                row["realized_net_return"],
                field="realized_net_return",
            )
            for row in admitted
        ),
        ZERO,
    )
    candidate_mean = (
        None
        if not admitted
        else candidate_sum / Decimal(len(admitted))
    )
    blocks = _cadence_blocks(rows)
    ready = (
        len(rows) >= config.validation_rows
        and len(admitted) >= config.min_validation_admitted
        and len(long_rows) >= config.min_validation_per_direction
        and len(short_rows) >= config.min_validation_per_direction
        and len(long_admitted) >= config.min_admitted_per_direction
        and len(short_admitted) >= config.min_admitted_per_direction
        and candidate_mean is not None
        and candidate_mean > ZERO
        and all(block["passes"] is True for block in blocks)
    )
    return {
        "ready_for_review": ready,
        "prospective_rows": len(rows),
        "required_prospective_rows": config.validation_rows,
        "admitted_rows": len(admitted),
        "required_admitted_rows": config.min_validation_admitted,
        "candidate_net_return_sum": str(candidate_sum),
        "candidate_mean_net_return": (
            None if candidate_mean is None else str(candidate_mean)
        ),
        "long_rows": len(long_rows),
        "short_rows": len(short_rows),
        "long_admitted_rows": len(long_admitted),
        "short_admitted_rows": len(short_admitted),
        "required_rows_per_direction": (
            config.min_validation_per_direction
        ),
        "required_admitted_per_direction": (
            config.min_admitted_per_direction
        ),
        "stability_blocks": blocks,
        "missing": {
            "prospective_rows": max(
                0,
                config.validation_rows - len(rows),
            ),
            "admitted_rows": max(
                0,
                config.min_validation_admitted - len(admitted),
            ),
            "long_rows": max(
                0,
                config.min_validation_per_direction - len(long_rows),
            ),
            "short_rows": max(
                0,
                config.min_validation_per_direction - len(short_rows),
            ),
            "long_admitted_rows": max(
                0,
                config.min_admitted_per_direction
                - len(long_admitted),
            ),
            "short_admitted_rows": max(
                0,
                config.min_admitted_per_direction
                - len(short_admitted),
            ),
            "passing_stability_blocks": sum(
                1 for block in blocks if block["passes"] is not True
            ),
        },
    }


def _comparison_summary(
    comparison: dict[str, object],
) -> dict[str, object]:
    rows = cast(
        tuple[dict[str, object], ...],
        comparison["rows"],
    )
    both = tuple(
        row
        for row in rows
        if row["microstructure_admitted"] is True
        and row["baseline_admitted"] is True
    )
    micro_only = tuple(
        row
        for row in rows
        if row["microstructure_admitted"] is True
        and row["baseline_admitted"] is False
    )
    baseline_only = tuple(
        row
        for row in rows
        if row["microstructure_admitted"] is False
        and row["baseline_admitted"] is True
    )
    neither = len(rows) - len(both) - len(micro_only) - len(baseline_only)

    def realized_sum(items: tuple[dict[str, object], ...]) -> Decimal:
        return sum(
            (
                _decimal(
                    row["realized_net_return"],
                    field="realized_net_return",
                )
                for row in items
            ),
            ZERO,
        )

    micro = tuple(
        row for row in rows if row["microstructure_admitted"] is True
    )
    baseline = tuple(
        row for row in rows if row["baseline_admitted"] is True
    )
    micro_sum = realized_sum(micro)
    baseline_sum = realized_sum(baseline)
    return {
        "paired_rows": len(rows),
        "required_paired_rows": DEFAULT_CONFIG.validation_rows,
        "paired_sample_complete": (
            len(rows) >= DEFAULT_CONFIG.validation_rows
        ),
        "both_admit": len(both),
        "microstructure_only": len(micro_only),
        "baseline_only": len(baseline_only),
        "neither": neither,
        "microstructure_admitted_sum": str(micro_sum),
        "baseline_admitted_sum": str(baseline_sum),
        "microstructure_minus_baseline_sum": str(
            micro_sum - baseline_sum
        ),
        "microstructure_only_realized_sum": str(
            realized_sum(micro_only)
        ),
        "baseline_only_realized_sum": str(
            realized_sum(baseline_only)
        ),
        "missing_paired_rows": max(
            0,
            DEFAULT_CONFIG.validation_rows - len(rows),
        ),
    }


def _timing_diagnostics(
    timing: dict[str, object],
) -> dict[str, int]:
    raw = timing.get("latest_diagnostics")
    if not isinstance(raw, dict):
        raise ProspectiveTradeQualityReadinessError(
            "timing latest_diagnostics must be an object"
        )
    fields = (
        "prospective_closed_trades",
        "paired_evaluable_trades",
        "missing_60s_outcomes",
        "missing_120s_outcomes",
        "non_evaluable_60s",
        "non_evaluable_120s",
        "lineage_mismatches",
    )
    result: dict[str, int] = {}
    for field in fields:
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProspectiveTradeQualityReadinessError(
                f"timing diagnostic {field} must be an integer"
            )
        if value < 0:
            raise ProspectiveTradeQualityReadinessError(
                f"timing diagnostic {field} must be non-negative"
            )
        result[field] = value
    return result


def _timing_readiness(timing: dict[str, object]) -> dict[str, object]:
    if _required_string(timing, "candidate_id") != TIMING_CANDIDATE_ID:
        raise ProspectiveTradeQualityReadinessError(
            "timing candidate ID drifted"
        )
    if timing.get("direction_policy") != "both_directions_remain_eligible":
        raise ProspectiveTradeQualityReadinessError(
            "timing direction policy drifted"
        )
    diagnostics = _timing_diagnostics(timing)
    rows = cast(tuple[dict[str, object], ...], timing["rows"])
    if _required_int(timing, "row_count") != len(rows):
        raise ProspectiveTradeQualityReadinessError(
            "timing row_count does not match rows"
        )
    if diagnostics["paired_evaluable_trades"] != len(rows):
        raise ProspectiveTradeQualityReadinessError(
            "timing paired-evaluable count does not match ledger rows"
        )

    long_rows = tuple(row for row in rows if row["direction"] == "long")
    short_rows = tuple(
        row for row in rows if row["direction"] == "short"
    )
    selected_sum = sum(
        (
            _decimal(row["selected_net_pnl"], field="selected_net_pnl")
            for row in rows
        ),
        ZERO,
    )
    delta_actual = sum(
        (
            _decimal(
                row["selected_minus_actual_pnl"],
                field="selected_minus_actual_pnl",
            )
            for row in rows
        ),
        ZERO,
    )
    delta_60s = sum(
        (
            _decimal(
                row["selected_minus_60s_pnl"],
                field="selected_minus_60s_pnl",
            )
            for row in rows
        ),
        ZERO,
    )
    integrity_clean = (
        diagnostics["missing_60s_outcomes"] == 0
        and diagnostics["missing_120s_outcomes"] == 0
        and diagnostics["lineage_mismatches"] == 0
    )
    ready = (
        diagnostics["prospective_closed_trades"]
        >= MIN_PROSPECTIVE_CLOSED_TRADES
        and len(rows) >= MIN_PAIRED_EVALUABLE_TRADES
        and len(long_rows) >= MIN_LONG_TRADES
        and len(short_rows) >= MIN_SHORT_TRADES
        and integrity_clean
    )
    return {
        "ready_for_review": ready,
        "integrity_clean": integrity_clean,
        "prospective_closed_trades": diagnostics[
            "prospective_closed_trades"
        ],
        "paired_evaluable_trades": len(rows),
        "long_rows": len(long_rows),
        "short_rows": len(short_rows),
        "selected_net_pnl": str(selected_sum),
        "selected_minus_actual_pnl": str(delta_actual),
        "selected_minus_60s_pnl": str(delta_60s),
        "diagnostics": diagnostics,
        "required": {
            "prospective_closed_trades": MIN_PROSPECTIVE_CLOSED_TRADES,
            "paired_evaluable_trades": MIN_PAIRED_EVALUABLE_TRADES,
            "long_rows": MIN_LONG_TRADES,
            "short_rows": MIN_SHORT_TRADES,
        },
        "missing": {
            "prospective_closed_trades": max(
                0,
                MIN_PROSPECTIVE_CLOSED_TRADES
                - diagnostics["prospective_closed_trades"],
            ),
            "paired_evaluable_trades": max(
                0,
                MIN_PAIRED_EVALUABLE_TRADES - len(rows),
            ),
            "long_rows": max(0, MIN_LONG_TRADES - len(long_rows)),
            "short_rows": max(0, MIN_SHORT_TRADES - len(short_rows)),
        },
    }


def prospective_trade_quality_readiness(
    prediction_raw: object,
    comparison_raw: object,
    timing_raw: object,
) -> dict[str, object]:
    try:
        prediction = validate_prediction_ledger(prediction_raw)
        comparison = validate_comparison_ledger(comparison_raw)
        timing = validate_timing_ledger(timing_raw)
    except RuntimeError as exc:
        raise ProspectiveTradeQualityReadinessError(str(exc)) from exc

    cadence_rows = _validate_cross_ledger_alignment(
        prediction,
        comparison,
    )
    cadence = _cadence_readiness(cadence_rows)
    comparison_summary = _comparison_summary(comparison)
    timing_summary = _timing_readiness(timing)
    any_ready = (
        cadence["ready_for_review"] is True
        or timing_summary["ready_for_review"] is True
    )
    return {
        "schema_version": 1,
        "kind": "prospective-trade-quality-readiness-v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "status": "review_ready" if any_ready else "collecting",
        "any_candidate_ready_for_review": any_ready,
        "cadence": {
            "model_family": prediction["model_family"],
            "prospective_start_ms": prediction["prospective_start_ms"],
            "frozen_training_rows": prediction["frozen_training_rows"],
            "frozen_training_rows_sha256": prediction[
                "frozen_training_rows_sha256"
            ],
            "prediction_ledger_sha256": prediction["ledger_sha256"],
            "comparison_ledger_sha256": comparison["ledger_sha256"],
            "ledger_alignment_clean": True,
            **cadence,
        },
        "comparison": comparison_summary,
        "timing": {
            "candidate_id": timing["candidate_id"],
            "started_at_ms": timing["started_at_ms"],
            "timing_ledger_sha256": timing["ledger_sha256"],
            **timing_summary,
        },
        "authority": {
            "paper_execution_change_allowed": False,
            "promotion_allowed": False,
            "live_execution_allowed": False,
            "meaning_of_ready": (
                "ready_for_review_only; separate frozen promotion "
                "authority is still required"
            ),
        },
    }
