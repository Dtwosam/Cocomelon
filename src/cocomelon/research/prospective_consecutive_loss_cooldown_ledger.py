from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.prospective_consecutive_loss_cooldown_shadow import (
    EMBARGO_MS,
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
    RELAXED_COOLDOWN_WINDOWS_MS,
    ProspectiveConsecutiveLossCooldownShadowState,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-consecutive-loss-cooldown-ledger-v1"
ZERO: Final = Decimal("0")
TERMINAL_MARKOUT_STATUSES: Final = frozenset({"settled", "stale"})


class ProspectiveConsecutiveLossCooldownLedgerError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def _required_string(
    raw: dict[str, object],
    key: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(
    raw: dict[str, object],
    key: str,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{key} must be an integer"
        )
    return value


def _required_bool(
    raw: dict[str, object],
    key: str,
) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{key} must be boolean"
        )
    return value


def _optional_string(
    raw: dict[str, object],
    key: str,
) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{key} must be null or a non-empty string"
        )
    return value


def _optional_decimal_string(
    raw: dict[str, object],
    key: str,
) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    return _decimal_string(value, field=key)


def _decimal_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{field} must be a string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{field} must be finite"
        )
    return value


def _string_list(
    raw: dict[str, object],
    key: str,
) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{key} must be a list"
        )
    if any(not isinstance(item, str) for item in value):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            f"{key} entries must be strings"
        )
    return list(value)


def _canonical_markout(
    raw: object,
    *,
    horizon_ms: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown markout must be an object"
        )
    status = _required_string(raw, "status")
    if status not in {
        "missing_path",
        "pending",
        "stale",
        "settled",
    }:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown markout status is unsupported"
        )
    if _required_int(raw, "horizon_ms") != horizon_ms:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown markout horizon drift"
        )
    target_at_ms = _required_int(raw, "target_at_ms")
    if target_at_ms < 0:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown markout target timestamp is invalid"
        )
    observed_at_ms = raw.get("observed_at_ms")
    lag_ms = raw.get("observation_lag_ms")
    mark_px = _optional_decimal_string(raw, "mark_px")
    directional_return = _optional_decimal_string(
        raw,
        "directional_return_fraction",
    )
    gross_pnl = _optional_decimal_string(
        raw,
        "gross_mark_to_market_pnl",
    )
    adjusted_pnl = _optional_decimal_string(
        raw,
        "entry_fee_adjusted_mark_to_market_pnl",
    )

    if status in {"missing_path", "pending"}:
        if any(
            value is not None
            for value in (
                observed_at_ms,
                lag_ms,
                mark_px,
                directional_return,
                gross_pnl,
                adjusted_pnl,
            )
        ):
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "pending cooldown markout contains settled fields"
            )
    else:
        if (
            isinstance(observed_at_ms, bool)
            or not isinstance(observed_at_ms, int)
            or observed_at_ms < target_at_ms
            or isinstance(lag_ms, bool)
            or not isinstance(lag_ms, int)
            or lag_ms != observed_at_ms - target_at_ms
            or mark_px is None
        ):
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "terminal cooldown markout timing is invalid"
            )
        if status == "settled":
            if (
                lag_ms > MAX_MARK_LAG_MS
                or directional_return is None
                or gross_pnl is None
                or adjusted_pnl is None
            ):
                raise ProspectiveConsecutiveLossCooldownLedgerError(
                    "settled cooldown markout is incomplete"
                )
        else:
            if (
                lag_ms <= MAX_MARK_LAG_MS
                or directional_return is not None
                or gross_pnl is not None
                or adjusted_pnl is not None
            ):
                raise ProspectiveConsecutiveLossCooldownLedgerError(
                    "stale cooldown markout is inconsistent"
                )

    return {
        "status": status,
        "horizon_ms": horizon_ms,
        "target_at_ms": target_at_ms,
        "observed_at_ms": observed_at_ms,
        "observation_lag_ms": lag_ms,
        "mark_px": mark_px,
        "directional_return_fraction": directional_return,
        "gross_mark_to_market_pnl": gross_pnl,
        "entry_fee_adjusted_mark_to_market_pnl": adjusted_pnl,
    }


def _window_applications(
    *,
    elapsed_ms: int,
    baseline_cooldown_ms: int,
) -> list[int]:
    return [
        window_ms
        for window_ms in RELAXED_COOLDOWN_WINDOWS_MS
        if elapsed_ms >= window_ms
        and baseline_cooldown_ms > window_ms
    ]


def _canonical_option(
    raw: object,
    *,
    started_at_ms: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown option row must be an object"
        )
    opportunity_id = _required_string(raw, "opportunity_id")
    timestamp_ms = _required_int(raw, "timestamp_ms")
    if timestamp_ms < started_at_ms:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown option predates clean start"
        )
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown option direction must be long or short"
        )
    lead_strategy = _required_string(raw, "lead_strategy")
    rank_ordinal = _required_int(raw, "rank_ordinal")
    if rank_ordinal <= 0:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown option rank must be positive"
        )
    consecutive_losses = _required_int(
        raw,
        "baseline_consecutive_losses",
    )
    elapsed_ms = _required_int(
        raw,
        "baseline_elapsed_since_last_close_ms",
    )
    baseline_cooldown_ms = _required_int(
        raw,
        "baseline_cooldown_ms",
    )
    if (
        consecutive_losses < 0
        or elapsed_ms < 0
        or baseline_cooldown_ms <= elapsed_ms
    ):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown option baseline state is invalid"
        )
    elapsed_bucket = _required_string(raw, "elapsed_bucket")
    expected_bucket = (
        "0-15m"
        if elapsed_ms < 15 * 60 * 1_000
        else (
            "15-30m"
            if elapsed_ms < 30 * 60 * 1_000
            else (
                "30-45m"
                if elapsed_ms < 45 * 60 * 1_000
                else "45m+"
            )
        )
    )
    if elapsed_bucket != expected_bucket:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown option elapsed bucket drift"
        )

    risk_approved = _required_bool(
        raw,
        "counterfactual_risk_approved",
    )
    risk_reasons = _string_list(
        raw,
        "counterfactual_risk_reason_codes",
    )
    planning_approved = _required_bool(raw, "planning_approved")
    planning_rejection = _optional_string(
        raw,
        "planning_rejection",
    )
    execution_result = _optional_string(raw, "execution_result")
    filled_quantity = _optional_decimal_string(
        raw,
        "filled_quantity",
    )
    average_fill_price = _optional_decimal_string(
        raw,
        "average_fill_price",
    )
    entry_fee = _optional_decimal_string(raw, "entry_fee")

    raw_markouts = raw.get("markouts")
    if not isinstance(raw_markouts, dict):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown option markouts must be an object"
        )
    expected_horizon_keys = {
        str(horizon_ms) for horizon_ms in FORWARD_HORIZONS_MS
    }
    if filled_quantity is None:
        if (
            average_fill_price is not None
            or entry_fee is not None
            or raw_markouts
        ):
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "unfilled cooldown option has fill evidence"
            )
        markouts: dict[str, object] = {}
        terminal = True
    else:
        if average_fill_price is None or entry_fee is None:
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "filled cooldown option is missing fill evidence"
            )
        if set(raw_markouts) != expected_horizon_keys:
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "filled cooldown option horizon set drift"
            )
        markouts = {
            str(horizon_ms): _canonical_markout(
                raw_markouts[str(horizon_ms)],
                horizon_ms=horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        }
        terminal = all(
            cast(dict[str, object], value)["status"]
            in TERMINAL_MARKOUT_STATUSES
            for value in markouts.values()
        )

    if not risk_approved:
        if (
            not risk_reasons
            or planning_approved
            or planning_rejection is not None
            or execution_result is not None
            or filled_quantity is not None
        ):
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "risk-rejected cooldown option is inconsistent"
            )
    elif not planning_approved:
        if (
            risk_reasons
            or planning_rejection is None
            or execution_result is not None
            or filled_quantity is not None
        ):
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "planning-rejected cooldown option is inconsistent"
            )
    else:
        if risk_reasons or planning_rejection is not None:
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "planned cooldown option carries rejection evidence"
            )
        if execution_result is None:
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "planned cooldown option is missing execution result"
            )

    return {
        "opportunity_id": opportunity_id,
        "timestamp_ms": timestamp_ms,
        "market": market,
        "direction": direction,
        "lead_strategy": lead_strategy,
        "rank_ordinal": rank_ordinal,
        "baseline_consecutive_losses": consecutive_losses,
        "baseline_elapsed_since_last_close_ms": elapsed_ms,
        "baseline_cooldown_ms": baseline_cooldown_ms,
        "elapsed_bucket": elapsed_bucket,
        "applicable_relaxed_windows_ms": _window_applications(
            elapsed_ms=elapsed_ms,
            baseline_cooldown_ms=baseline_cooldown_ms,
        ),
        "counterfactual_risk_approved": risk_approved,
        "counterfactual_risk_reason_codes": risk_reasons,
        "planning_approved": planning_approved,
        "planning_rejection": planning_rejection,
        "execution_result": execution_result,
        "filled_quantity": filled_quantity,
        "average_fill_price": average_fill_price,
        "entry_fee": entry_fee,
        "markouts": markouts,
        "terminal": terminal,
    }


def _row_identity(row: dict[str, object]) -> tuple[int, str]:
    return (
        cast(int, row["timestamp_ms"]),
        cast(str, row["opportunity_id"]),
    )


def _canonical_rows(
    raw: object,
    *,
    started_at_ms: int,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger rows must be a list"
        )
    rows = tuple(
        _canonical_option(row, started_at_ms=started_at_ms)
        for row in raw
    )
    if any(row["terminal"] is not True for row in rows):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger contains non-terminal row"
        )
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "duplicate cooldown ledger row identity"
        )
    opportunity_ids = tuple(
        cast(str, row["opportunity_id"]) for row in rows
    )
    if len(opportunity_ids) != len(set(opportunity_ids)):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "duplicate cooldown ledger opportunity id"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _robustness(
    rows: tuple[dict[str, object], ...],
    *,
    window_ms: int,
) -> dict[str, object]:
    horizon_key = str(60 * 60 * 1_000)
    settled: list[tuple[str, Decimal]] = []
    for row in rows:
        windows = row.get("applicable_relaxed_windows_ms")
        if not isinstance(windows, list) or window_ms not in windows:
            continue
        markouts = row.get("markouts")
        if not isinstance(markouts, dict):
            continue
        raw_markout = markouts.get(horizon_key)
        if not isinstance(raw_markout, dict):
            continue
        if raw_markout.get("status") != "settled":
            continue
        raw_pnl = raw_markout.get(
            "entry_fee_adjusted_mark_to_market_pnl"
        )
        if not isinstance(raw_pnl, str):
            continue
        settled.append(
            (cast(str, row["market"]), Decimal(raw_pnl))
        )
    total = sum((pnl for _market, pnl in settled), ZERO)
    leave_option = tuple(total - pnl for _market, pnl in settled)
    by_market: dict[str, Decimal] = {}
    for market, pnl in settled:
        by_market[market] = by_market.get(market, ZERO) + pnl
    leave_market = tuple(
        total - market_pnl for market_pnl in by_market.values()
    )
    return {
        "settled_options": len(settled),
        "market_count": len(by_market),
        "total_entry_fee_adjusted_1h_pnl": str(total),
        "leave_one_option_out_min_pnl": str(
            min(leave_option, default=ZERO)
        ),
        "positive_after_removing_any_one_option": (
            len(settled) >= 2
            and min(leave_option, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_pnl": str(
            min(leave_market, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(by_market) >= 2
            and min(leave_market, default=ZERO) > ZERO
        ),
    }


def _summary(
    rows: tuple[dict[str, object], ...],
    *,
    pending_option_count: int,
) -> dict[str, object]:
    by_direction: dict[str, dict[str, int]] = {}
    for direction in ("long", "short"):
        cohort = tuple(
            row for row in rows if row["direction"] == direction
        )
        by_direction[direction] = {
            "terminal_options": len(cohort),
            "filled_options": sum(
                row["filled_quantity"] is not None for row in cohort
            ),
        }

    relaxation_windows: dict[str, dict[str, object]] = {}
    for window_ms in RELAXED_COOLDOWN_WINDOWS_MS:
        candidates = tuple(
            row
            for row in rows
            if window_ms
            in cast(list[int], row["applicable_relaxed_windows_ms"])
        )
        relaxation_windows[str(window_ms)] = {
            "terminal_options": len(candidates),
            "filled_options": sum(
                row["filled_quantity"] is not None
                for row in candidates
            ),
            "robustness": _robustness(
                rows,
                window_ms=window_ms,
            ),
        }

    return {
        "terminal_option_count": len(rows),
        "pending_option_count": pending_option_count,
        "filled_terminal_options": sum(
            row["filled_quantity"] is not None for row in rows
        ),
        "risk_rejected_terminal_options": sum(
            row["counterfactual_risk_approved"] is False
            for row in rows
        ),
        "planning_rejected_terminal_options": sum(
            row["counterfactual_risk_approved"] is True
            and row["planning_approved"] is False
            for row in rows
        ),
        "unfilled_execution_terminal_options": sum(
            row["planning_approved"] is True
            and row["filled_quantity"] is None
            for row in rows
        ),
        "by_direction": by_direction,
        "relaxation_windows": relaxation_windows,
    }


def _validate_metadata(
    raw: dict[str, object],
) -> ProspectiveConsecutiveLossCooldownShadowState:
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger kind is unsupported"
        )
    candidate_id = _required_string(raw, "candidate_id")
    frozen_at_ms = _required_int(raw, "frozen_at_ms")
    started_at_ms = _required_int(raw, "started_at_ms")
    if frozen_at_ms < 0:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger freeze must be non-negative"
        )
    try:
        state = ProspectiveConsecutiveLossCooldownShadowState(
            frozen_at_ms=frozen_at_ms,
            candidate_id=candidate_id,
        )
    except ValueError as exc:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            str(exc)
        ) from exc
    expected = state.payload()
    if started_at_ms != state.started_at_ms:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger clean start drift"
        )
    for key in (
        "embargo_ms",
        "relaxed_cooldown_windows_ms",
        "forward_horizons_ms",
        "max_mark_lag_ms",
        "rule",
    ):
        if raw.get(key) != expected[key]:
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                f"cooldown ledger metadata drift: {key}"
            )
    return state


def validate_cooldown_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger must be an object"
        )
    state = _validate_metadata(raw)
    rows = _canonical_rows(
        raw.get("rows"),
        started_at_ms=state.started_at_ms,
    )
    if raw.get("row_count") != len(rows):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger row digest mismatch"
        )
    pending_count = _required_int(raw, "pending_option_count")
    if pending_count < 0:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger pending count is invalid"
        )
    if raw.get("summary") != _summary(
        rows,
        pending_option_count=pending_count,
    ):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger summary does not reconcile"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger source history must be a list"
        )
    expected_digest = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_digest:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_cooldown_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown ledger file is invalid"
        ) from exc
    return validate_cooldown_ledger(raw)


def _source_rows(
    summary: object,
    state: ProspectiveConsecutiveLossCooldownShadowState,
) -> tuple[tuple[dict[str, object], ...], int]:
    if not isinstance(summary, dict):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown shadow summary must be an object"
        )
    expected = state.payload()
    for key in (
        "candidate_id",
        "frozen_at_ms",
        "started_at_ms",
        "embargo_ms",
        "relaxed_cooldown_windows_ms",
        "forward_horizons_ms",
        "max_mark_lag_ms",
    ):
        if summary.get(key) != expected[key]:
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                f"cooldown shadow source drift: {key}"
            )
    if (
        summary.get("research_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("changes_risk_limits") is not False
        or summary.get("forward_markout_only") is not True
        or summary.get("replacement_exits_modeled") is not False
        or summary.get("realized_pnl_modeled") is not False
    ):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown shadow source authority or claim scope drift"
        )
    raw_options = summary.get("option_results")
    if not isinstance(raw_options, list):
        raise ProspectiveConsecutiveLossCooldownLedgerError(
            "cooldown shadow option results must be a list"
        )
    terminal_rows: list[dict[str, object]] = []
    pending = 0
    for raw_option in raw_options:
        row = _canonical_option(
            raw_option,
            started_at_ms=state.started_at_ms,
        )
        if row["terminal"] is True:
            terminal_rows.append(row)
        else:
            pending += 1
    return (
        _canonical_rows(
            tuple(terminal_rows),
            started_at_ms=state.started_at_ms,
        ),
        pending,
    )


def update_cooldown_ledger(
    summary: object,
    state: ProspectiveConsecutiveLossCooldownShadowState,
    *,
    previous: dict[str, object] | None,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_artifact_name: str,
    source_artifact_digest: str,
) -> dict[str, object]:
    if source_paper_run_id <= 0 or source_paper_run_attempt <= 0:
        raise ValueError("source paper run identity must be positive")
    if not source_artifact_name.strip():
        raise ValueError("source artifact name must not be empty")
    if not source_artifact_digest.startswith("sha256:"):
        raise ValueError("source artifact digest must be sha256")

    rows, pending_count = _source_rows(summary, state)
    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None

    if previous is not None:
        validated = validate_cooldown_ledger(previous)
        expected = state.payload()
        for key in (
            "candidate_id",
            "frozen_at_ms",
            "started_at_ms",
            "embargo_ms",
            "relaxed_cooldown_windows_ms",
            "forward_horizons_ms",
            "max_mark_lag_ms",
            "rule",
        ):
            if validated.get(key) != expected[key]:
                raise ProspectiveConsecutiveLossCooldownLedgerError(
                    f"cooldown ledger metadata drift: {key}"
                )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveConsecutiveLossCooldownLedgerError(
                "cooldown ledger source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveConsecutiveLossCooldownLedgerError(
                    "cooldown ledger source history entry is invalid"
                )
            if (
                item.get("paper_run_id") == source_paper_run_id
                and item.get("paper_run_attempt")
                == source_paper_run_attempt
            ):
                if (
                    item.get("artifact_name")
                    != source_artifact_name
                    or item.get("artifact_digest")
                    != source_artifact_digest
                ):
                    raise ProspectiveConsecutiveLossCooldownLedgerError(
                        "duplicate cooldown source artifact drift"
                    )
                return validated

        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        history = list(raw_history)
        prior_ledger_sha256 = cast(
            str,
            validated["ledger_sha256"],
        )
        current_by_id = {
            cast(str, row["opportunity_id"]): row
            for row in rows
        }
        for old in previous_rows:
            opportunity_id = cast(str, old["opportunity_id"])
            current = current_by_id.get(opportunity_id)
            if current is None:
                raise ProspectiveConsecutiveLossCooldownLedgerError(
                    "previous terminal cooldown row disappeared"
                )
            if current != old:
                raise ProspectiveConsecutiveLossCooldownLedgerError(
                    "previous terminal cooldown row changed"
                )

    old_ids = {
        cast(str, row["opportunity_id"])
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in rows
        if cast(str, row["opportunity_id"]) not in old_ids
    )
    history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "artifact_name": source_artifact_name,
            "artifact_digest": source_artifact_digest,
            "terminal_row_count": len(rows),
            "new_terminal_row_count": len(new_rows),
            "pending_option_count": pending_count,
            "rows_sha256": _rows_sha256(rows),
        }
    )

    metadata = state.payload()
    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "relaxed_cooldown_windows_ms": list(
            RELAXED_COOLDOWN_WINDOWS_MS
        ),
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "rule": metadata["rule"],
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "pending_option_count": pending_count,
        "rows_sha256": _rows_sha256(rows),
        "source_history": history,
        "summary": _summary(
            rows,
            pending_option_count=pending_count,
        ),
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
