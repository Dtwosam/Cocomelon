from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-full-stack-reflow-exact-ledger-v1"
ZERO: Final = Decimal("0")
MIN_EXACT_OPTIONS_PER_HORIZON: Final = 20
MIN_EXACT_OPTIONS_PER_DIRECTION: Final = 5
MIN_EXACT_MARKETS: Final = 4


class ProspectiveFullStackReflowExactLedgerError(RuntimeError):
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
        raise ProspectiveFullStackReflowExactLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(
    raw: dict[str, object],
    key: str,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveFullStackReflowExactLedgerError(
            f"{key} must be an integer"
        )
    return value


def _decimal_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveFullStackReflowExactLedgerError(
            f"{field} must be a string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveFullStackReflowExactLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveFullStackReflowExactLedgerError(
            f"{field} must be finite"
        )
    return value


def _integer_list(
    raw: dict[str, object],
    key: str,
) -> list[int]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ProspectiveFullStackReflowExactLedgerError(
            f"{key} must be a list"
        )
    output: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ProspectiveFullStackReflowExactLedgerError(
                f"{key} entries must be integers"
            )
        output.append(item)
    return output


def _campaign_metadata(
    summary: dict[str, object],
) -> tuple[int, tuple[int, ...]]:
    overlap_started_at_ms = _required_int(
        summary,
        "overlap_started_at_ms",
    )
    if overlap_started_at_ms < 0:
        raise ProspectiveFullStackReflowExactLedgerError(
            "overlap_started_at_ms must be non-negative"
        )

    realized = summary.get("realized_pnl")
    if not isinstance(realized, dict):
        raise ProspectiveFullStackReflowExactLedgerError(
            "realized_pnl summary must be an object"
        )
    horizons = tuple(_integer_list(realized, "horizons_ms"))
    if (
        not horizons
        or any(value <= 0 for value in horizons)
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise ProspectiveFullStackReflowExactLedgerError(
            "realized PnL horizons must be positive and ordered"
        )
    return overlap_started_at_ms, horizons


def _validate_authority(summary: dict[str, object]) -> None:
    if summary.get("research_only") is not True:
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack summary must be research-only"
        )
    if summary.get("execution_authority") is not False:
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack summary must not grant execution authority"
        )
    if summary.get("promotion_authority") is not False:
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack summary must not grant promotion authority"
        )
    if summary.get("portfolio_counterfactual") is not False:
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack summary cannot claim a portfolio counterfactual"
        )
    if summary.get("cross_horizon_economics_aggregated") is not False:
        raise ProspectiveFullStackReflowExactLedgerError(
            "cross-horizon economics must remain separate"
        )
    if summary.get("strategy_level_realized_pnl_claimed") is not False:
        raise ProspectiveFullStackReflowExactLedgerError(
            "strategy-level realized PnL must remain unclaimed"
        )


def _canonical_exact_row(
    option: dict[str, object],
    exit_row: dict[str, object],
    *,
    horizon_ms: int,
) -> dict[str, object]:
    option_id = _required_string(option, "option_id")
    opportunity_id = _required_string(option, "opportunity_id")
    opportunity_timestamp_ms = _required_int(
        option,
        "opportunity_timestamp_ms",
    )
    market = _required_string(option, "opportunity_market")
    direction = _required_string(option, "opportunity_direction")
    if direction not in {"long", "short"}:
        raise ProspectiveFullStackReflowExactLedgerError(
            "replacement direction must be long or short"
        )
    entry_quantity = _decimal_string(
        option.get("entry_quantity"),
        field="entry_quantity",
    )
    if Decimal(entry_quantity) <= ZERO:
        raise ProspectiveFullStackReflowExactLedgerError(
            "entry_quantity must be positive"
        )
    entry_attempt_timestamp_ms = _required_int(
        option,
        "entry_attempt_timestamp_ms",
    )
    if exit_row.get("status") != "simulated":
        raise ProspectiveFullStackReflowExactLedgerError(
            "exact replacement exit must be simulated"
        )
    if exit_row.get("complete_close") is not True:
        raise ProspectiveFullStackReflowExactLedgerError(
            "exact replacement exit must fully close"
        )
    if exit_row.get("incomplete_reason") is not None:
        raise ProspectiveFullStackReflowExactLedgerError(
            "exact replacement exit cannot be incomplete"
        )
    if _required_int(exit_row, "horizon_ms") != horizon_ms:
        raise ProspectiveFullStackReflowExactLedgerError(
            "replacement horizon identity drift"
        )
    funding_boundary_count = _required_int(
        exit_row,
        "funding_boundary_count",
    )
    funding_boundaries_ms = _integer_list(
        exit_row,
        "funding_boundaries_ms",
    )
    funding_evidence_count = _required_int(
        exit_row,
        "funding_evidence_count",
    )
    missing_funding_boundaries_ms = _integer_list(
        exit_row,
        "missing_funding_boundaries_ms",
    )
    if len(funding_boundaries_ms) != funding_boundary_count:
        raise ProspectiveFullStackReflowExactLedgerError(
            "funding boundary count does not reconcile"
        )
    if funding_evidence_count != funding_boundary_count:
        raise ProspectiveFullStackReflowExactLedgerError(
            "exact replacement exit lacks complete funding evidence"
        )
    if missing_funding_boundaries_ms:
        raise ProspectiveFullStackReflowExactLedgerError(
            "exact replacement exit has missing funding evidence"
        )
    funding_cash_pnl = _decimal_string(
        exit_row.get("funding_cash_pnl"),
        field="funding_cash_pnl",
    )
    exact_realized_pnl = _decimal_string(
        exit_row.get("exact_realized_pnl"),
        field="exact_realized_pnl",
    )
    return {
        "option_id": option_id,
        "opportunity_id": opportunity_id,
        "opportunity_timestamp_ms": opportunity_timestamp_ms,
        "opportunity_market": market,
        "opportunity_direction": direction,
        "entry_quantity": entry_quantity,
        "entry_attempt_timestamp_ms": entry_attempt_timestamp_ms,
        "horizon_ms": horizon_ms,
        "funding_boundary_count": funding_boundary_count,
        "funding_boundaries_ms": funding_boundaries_ms,
        "funding_evidence_count": funding_evidence_count,
        "funding_cash_pnl": funding_cash_pnl,
        "exact_realized_pnl": exact_realized_pnl,
    }


def _exact_rows(
    summary: dict[str, object],
    *,
    horizons: tuple[int, ...],
) -> tuple[dict[str, object], ...]:
    realized = summary.get("realized_pnl")
    if not isinstance(realized, dict):
        raise ProspectiveFullStackReflowExactLedgerError(
            "realized_pnl summary must be an object"
        )
    raw_options = realized.get("option_results")
    if not isinstance(raw_options, list):
        raise ProspectiveFullStackReflowExactLedgerError(
            "realized PnL option_results must be a list"
        )

    rows: list[dict[str, object]] = []
    seen_options: set[str] = set()
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            raise ProspectiveFullStackReflowExactLedgerError(
                "realized PnL option must be an object"
            )
        option_id = _required_string(raw_option, "option_id")
        if option_id in seen_options:
            raise ProspectiveFullStackReflowExactLedgerError(
                "duplicate replacement option id"
            )
        seen_options.add(option_id)
        raw_exits = raw_option.get("exits")
        if not isinstance(raw_exits, dict):
            raise ProspectiveFullStackReflowExactLedgerError(
                "realized PnL exits must be an object"
            )
        for horizon_ms in horizons:
            raw_exit = raw_exits.get(str(horizon_ms))
            if not isinstance(raw_exit, dict):
                continue
            if raw_exit.get("exact_realized_pnl") is None:
                continue
            rows.append(
                _canonical_exact_row(
                    raw_option,
                    raw_exit,
                    horizon_ms=horizon_ms,
                )
            )

    rows.sort(
        key=lambda row: (
            cast(int, row["opportunity_timestamp_ms"]),
            cast(str, row["option_id"]),
            cast(int, row["horizon_ms"]),
        )
    )
    identities = tuple(
        (
            cast(str, row["option_id"]),
            cast(int, row["horizon_ms"]),
        )
        for row in rows
    )
    if len(identities) != len(set(identities)):
        raise ProspectiveFullStackReflowExactLedgerError(
            "duplicate exact option-horizon identity"
        )
    return tuple(rows)


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _horizon_summary(
    rows: tuple[dict[str, object], ...],
    *,
    horizon_ms: int,
) -> dict[str, object]:
    values = tuple(
        row for row in rows if row["horizon_ms"] == horizon_ms
    )
    total_pnl = sum(
        (Decimal(cast(str, row["exact_realized_pnl"])) for row in values),
        ZERO,
    )
    leave_option = tuple(
        total_pnl - Decimal(cast(str, row["exact_realized_pnl"]))
        for row in values
    )
    by_market: dict[str, Decimal] = {}
    for row in values:
        market = cast(str, row["opportunity_market"])
        by_market[market] = (
            by_market.get(market, ZERO)
            + Decimal(cast(str, row["exact_realized_pnl"]))
        )
    leave_market = tuple(
        total_pnl - market_pnl
        for market_pnl in by_market.values()
    )
    long_count = sum(
        row["opportunity_direction"] == "long" for row in values
    )
    short_count = sum(
        row["opportunity_direction"] == "short" for row in values
    )
    market_count = len(by_market)
    sample_complete = (
        len(values) >= MIN_EXACT_OPTIONS_PER_HORIZON
        and long_count >= MIN_EXACT_OPTIONS_PER_DIRECTION
        and short_count >= MIN_EXACT_OPTIONS_PER_DIRECTION
        and market_count >= MIN_EXACT_MARKETS
    )
    economics_positive = total_pnl > ZERO
    option_robust = (
        len(values) >= 2
        and min(leave_option, default=ZERO) > ZERO
    )
    market_robust = (
        market_count >= 2
        and min(leave_market, default=ZERO) > ZERO
    )
    return {
        "horizon_ms": horizon_ms,
        "exact_option_horizons": len(values),
        "long_exact_options": long_count,
        "short_exact_options": short_count,
        "market_count": market_count,
        "total_exact_realized_pnl": str(total_pnl),
        "leave_one_option_out_min_pnl": (
            None if not leave_option else str(min(leave_option))
        ),
        "leave_one_market_out_min_pnl": (
            None if not leave_market else str(min(leave_market))
        ),
        "review_readiness": {
            "sample_complete": sample_complete,
            "economics_positive": economics_positive,
            "single_option_robust": option_robust,
            "single_market_robust": market_robust,
            "ready_for_evidence_review": (
                sample_complete
                and economics_positive
                and option_robust
                and market_robust
            ),
            "min_exact_options": MIN_EXACT_OPTIONS_PER_HORIZON,
            "min_exact_per_direction": (
                MIN_EXACT_OPTIONS_PER_DIRECTION
            ),
            "min_exact_markets": MIN_EXACT_MARKETS,
            "missing_exact_options": max(
                0,
                MIN_EXACT_OPTIONS_PER_HORIZON - len(values),
            ),
            "missing_long_exact_options": max(
                0,
                MIN_EXACT_OPTIONS_PER_DIRECTION - long_count,
            ),
            "missing_short_exact_options": max(
                0,
                MIN_EXACT_OPTIONS_PER_DIRECTION - short_count,
            ),
            "missing_exact_markets": max(
                0,
                MIN_EXACT_MARKETS - market_count,
            ),
            "changes_execution": False,
            "changes_readiness_gate": False,
        },
    }


def _summary(
    rows: tuple[dict[str, object], ...],
    *,
    horizons: tuple[int, ...],
) -> dict[str, object]:
    return {
        "cross_horizon_economics_aggregated": False,
        "strategy_level_realized_pnl_claimed": False,
        "portfolio_counterfactual_complete": False,
        "by_horizon": {
            str(horizon_ms): _horizon_summary(
                rows,
                horizon_ms=horizon_ms,
            )
            for horizon_ms in horizons
        },
    }


def validate_full_stack_reflow_exact_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack reflow exact ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack reflow exact ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack reflow exact ledger kind is unsupported"
        )
    overlap_started_at_ms = _required_int(
        raw,
        "overlap_started_at_ms",
    )
    if overlap_started_at_ms < 0:
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger overlap start is invalid"
        )
    horizons = tuple(_integer_list(raw, "horizons_ms"))
    if (
        not horizons
        or any(value <= 0 for value in horizons)
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger horizons are invalid"
        )
    raw_rows = raw.get("rows")
    if not isinstance(raw_rows, (list, tuple)):
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger rows must be a list"
        )
    rows = tuple(
        _canonical_exact_row(
            cast(dict[str, object], row),
            {
                "status": "simulated",
                "complete_close": True,
                "incomplete_reason": None,
                "horizon_ms": cast(dict[str, object], row).get(
                    "horizon_ms"
                ),
                "funding_boundary_count": cast(
                    dict[str, object],
                    row,
                ).get("funding_boundary_count"),
                "funding_boundaries_ms": cast(
                    dict[str, object],
                    row,
                ).get("funding_boundaries_ms"),
                "funding_evidence_count": cast(
                    dict[str, object],
                    row,
                ).get("funding_evidence_count"),
                "missing_funding_boundaries_ms": [],
                "funding_cash_pnl": cast(
                    dict[str, object],
                    row,
                ).get("funding_cash_pnl"),
                "exact_realized_pnl": cast(
                    dict[str, object],
                    row,
                ).get("exact_realized_pnl"),
            },
            horizon_ms=_required_int(
                cast(dict[str, object], row),
                "horizon_ms",
            ),
        )
        for row in raw_rows
    )
    identities = tuple(
        (
            cast(str, row["option_id"]),
            cast(int, row["horizon_ms"]),
        )
        for row in rows
    )
    if len(identities) != len(set(identities)):
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger contains duplicate option-horizon rows"
        )
    if raw.get("row_count") != len(rows):
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger row digest mismatch"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger source history must be a list"
        )
    if raw.get("summary") != _summary(rows, horizons=horizons):
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger summary does not reconcile"
        )
    expected_digest = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_digest:
        raise ProspectiveFullStackReflowExactLedgerError(
            "ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_full_stack_reflow_exact_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveFullStackReflowExactLedgerError(
            "full-stack reflow exact ledger file is invalid"
        ) from exc
    return validate_full_stack_reflow_exact_ledger(raw)


def update_full_stack_reflow_exact_ledger(
    full_stack_summary: dict[str, object],
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

    _validate_authority(full_stack_summary)
    overlap_started_at_ms, horizons = _campaign_metadata(
        full_stack_summary
    )
    current_rows = _exact_rows(
        full_stack_summary,
        horizons=horizons,
    )

    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_full_stack_reflow_exact_ledger(
            previous
        )
        if (
            validated.get("overlap_started_at_ms")
            != overlap_started_at_ms
        ):
            raise ProspectiveFullStackReflowExactLedgerError(
                "full-stack reflow campaign start drift"
            )
        if validated.get("horizons_ms") != list(horizons):
            raise ProspectiveFullStackReflowExactLedgerError(
                "full-stack reflow horizon set drift"
            )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveFullStackReflowExactLedgerError(
                "previous source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveFullStackReflowExactLedgerError(
                    "previous source history entry is invalid"
                )
            if (
                item.get("paper_run_id") == source_paper_run_id
                and item.get("paper_run_attempt")
                == source_paper_run_attempt
            ):
                if (
                    item.get("artifact_name") != source_artifact_name
                    or item.get("artifact_digest")
                    != source_artifact_digest
                ):
                    raise ProspectiveFullStackReflowExactLedgerError(
                        "duplicate source artifact identity drift"
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
        current_by_identity = {
            (
                cast(str, row["option_id"]),
                cast(int, row["horizon_ms"]),
            ): row
            for row in current_rows
        }
        for old in previous_rows:
            identity = (
                cast(str, old["option_id"]),
                cast(int, old["horizon_ms"]),
            )
            current = current_by_identity.get(identity)
            if current is None:
                raise ProspectiveFullStackReflowExactLedgerError(
                    "previous exact option-horizon row disappeared"
                )
            if current != old:
                raise ProspectiveFullStackReflowExactLedgerError(
                    "previous exact option-horizon row changed"
                )

    old_identities = {
        (
            cast(str, row["option_id"]),
            cast(int, row["horizon_ms"]),
        )
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in current_rows
        if (
            cast(str, row["option_id"]),
            cast(int, row["horizon_ms"]),
        )
        not in old_identities
    )
    total_option_horizons = 0
    realized = full_stack_summary.get("realized_pnl")
    if isinstance(realized, dict):
        raw_options = realized.get("option_results")
        if isinstance(raw_options, list):
            total_option_horizons = len(raw_options) * len(horizons)
    pending_option_horizons = max(
        0,
        total_option_horizons - len(current_rows),
    )

    history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "artifact_name": source_artifact_name,
            "artifact_digest": source_artifact_digest,
            "row_count": len(current_rows),
            "new_row_count": len(new_rows),
            "pending_option_horizons": pending_option_horizons,
            "rows_sha256": _rows_sha256(current_rows),
        }
    )

    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "overlap_started_at_ms": overlap_started_at_ms,
        "horizons_ms": list(horizons),
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(current_rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "pending_option_horizons": pending_option_horizons,
        "rows_sha256": _rows_sha256(current_rows),
        "source_history": history,
        "summary": _summary(current_rows, horizons=horizons),
        "rows": current_rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
