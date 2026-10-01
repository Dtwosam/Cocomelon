from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_RULES,
)
from cocomelon.research.profit_lock_execution_readiness import (
    profit_lock_execution_readiness,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "profit-lock-execution-shadow-ledger-v1"
ZERO: Final = Decimal("0")


class ProfitLockExecutionLedgerError(RuntimeError):
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


def _required_int(
    raw: Mapping[str, object],
    key: str,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfitLockExecutionLedgerError(
            f"{key} must be an integer"
        )
    return value


def _nonnegative_int(
    raw: Mapping[str, object],
    key: str,
) -> int:
    value = _required_int(raw, key)
    if value < 0:
        raise ProfitLockExecutionLedgerError(
            f"{key} must be non-negative"
        )
    return value


def _required_string(
    raw: Mapping[str, object],
    key: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProfitLockExecutionLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _expected_rules() -> list[dict[str, str]]:
    return [
        {
            "rule_id": rule.rule_id,
            "activate_at_r": str(rule.activate_at_r),
            "lock_at_r": str(rule.lock_at_r),
        }
        for rule in DEFAULT_PROFIT_LOCK_RULES
    ]


def _row_identity(
    row: Mapping[str, object],
) -> tuple[str, str]:
    return (
        cast(str, row["trade_id"]),
        cast(str, row["rule_id"]),
    )


def _canonical_outcome(raw: object) -> dict[str, object]:
    try:
        outcome = ProfitLockExecutionOutcome.from_payload(raw)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ProfitLockExecutionLedgerError(
            "execution-shadow outcome is invalid"
        ) from exc
    return outcome.payload()


def _canonical_rows(
    raw: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProfitLockExecutionLedgerError(
            "execution-shadow outcomes must be a list"
        )
    rows = tuple(_canonical_outcome(item) for item in raw)
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProfitLockExecutionLedgerError(
            "duplicate execution-shadow outcome identity"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfitLockExecutionLedgerError(
            "economic value must be a decimal string or null"
        )
    resolved = Decimal(value)
    if not resolved.is_finite():
        raise ProfitLockExecutionLedgerError(
            "economic value must be finite"
        )
    return resolved


def _rule_summary(
    rows: tuple[dict[str, object], ...],
    rule_id: str,
) -> dict[str, object]:
    outcomes = tuple(
        row for row in rows if row["rule_id"] == rule_id
    )
    evaluated = tuple(
        row
        for row in outcomes
        if row["candidate_net_pnl_estimate"] is not None
    )
    actual_pnl = sum(
        (
            cast(Decimal, _decimal_or_none(row["actual_net_pnl"]))
            for row in evaluated
        ),
        ZERO,
    )
    candidate_pnl = sum(
        (
            cast(
                Decimal,
                _decimal_or_none(
                    row["candidate_net_pnl_estimate"]
                ),
            )
            for row in evaluated
        ),
        ZERO,
    )
    actual_r = sum(
        (
            cast(Decimal, _decimal_or_none(row["actual_net_r"]))
            for row in evaluated
        ),
        ZERO,
    )
    candidate_r = sum(
        (
            cast(
                Decimal,
                _decimal_or_none(
                    row["candidate_net_r_estimate"]
                ),
            )
            for row in evaluated
        ),
        ZERO,
    )
    count = len(evaluated)
    rule = next(
        item
        for item in DEFAULT_PROFIT_LOCK_RULES
        if item.rule_id == rule_id
    )
    return {
        "rule_id": rule_id,
        "activate_at_r": str(rule.activate_at_r),
        "lock_at_r": str(rule.lock_at_r),
        "closed_eligible_trades": len(outcomes),
        "economically_evaluated_trades": count,
        "activated_trades": sum(
            row["activated"] is True for row in outcomes
        ),
        "triggered_trades": sum(
            row["triggered"] is True for row in outcomes
        ),
        "simulated_full_closes": sum(
            row["simulated_close_complete"] is True
            for row in outcomes
        ),
        "triggered_incomplete": sum(
            row["candidate_source"] == "triggered_incomplete"
            for row in outcomes
        ),
        "actual_positive_trades": sum(
            cast(Decimal, _decimal_or_none(row["actual_net_pnl"]))
            > ZERO
            for row in evaluated
        ),
        "candidate_positive_trades_estimate": sum(
            cast(
                Decimal,
                _decimal_or_none(
                    row["candidate_net_pnl_estimate"]
                ),
            )
            > ZERO
            for row in evaluated
        ),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl_estimate": str(candidate_pnl),
        "delta_net_pnl_estimate": str(
            candidate_pnl - actual_pnl
        ),
        "actual_mean_net_r": (
            None
            if not evaluated
            else str(actual_r / Decimal(count))
        ),
        "candidate_mean_net_r_estimate": (
            None
            if not evaluated
            else str(candidate_r / Decimal(count))
        ),
        "delta_mean_net_r_estimate": (
            None
            if not evaluated
            else str(
                candidate_r / Decimal(count)
                - actual_r / Decimal(count)
            )
        ),
    }


def _readiness_payload(
    rule_summaries: tuple[dict[str, object], ...],
    *,
    lineage_mismatch_closed_trades: int,
    orphaned_restored_positions: int,
) -> dict[str, object]:
    readiness = profit_lock_execution_readiness(
        {
            "execution_authority": False,
            "rules": rule_summaries,
            "lineage_mismatch_closed_trades": (
                lineage_mismatch_closed_trades
            ),
            "orphaned_restored_positions": (
                orphaned_restored_positions
            ),
        }
    )
    return {
        "all_rules_ready_for_review": (
            readiness.all_rules_ready_for_review
        ),
        "promotion_authority": readiness.promotion_authority,
        "execution_authority": readiness.execution_authority,
        "lineage_mismatch_closed_trades": (
            readiness.lineage_mismatch_closed_trades
        ),
        "orphaned_restored_positions": (
            readiness.orphaned_restored_positions
        ),
        "rules": [
            {
                "rule_id": rule.rule_id,
                "economically_evaluated_trades": (
                    rule.economically_evaluated_trades
                ),
                "activated_trades": rule.activated_trades,
                "triggered_trades": rule.triggered_trades,
                "simulated_full_closes": (
                    rule.simulated_full_closes
                ),
                "triggered_incomplete": rule.triggered_incomplete,
                "missing_evaluated_trades": (
                    rule.missing_evaluated_trades
                ),
                "missing_activated_trades": (
                    rule.missing_activated_trades
                ),
                "missing_triggered_trades": (
                    rule.missing_triggered_trades
                ),
                "missing_simulated_full_closes": (
                    rule.missing_simulated_full_closes
                ),
                "status": rule.status.value,
            }
            for rule in readiness.rules
        ],
    }


def _economic_robustness(
    rows: tuple[dict[str, object], ...],
    rule_id: str,
) -> dict[str, object]:
    evaluated = tuple(
        row
        for row in rows
        if row["rule_id"] == rule_id
        and row["delta_net_pnl_estimate"] is not None
    )
    pnl_deltas = tuple(
        cast(
            Decimal,
            _decimal_or_none(row["delta_net_pnl_estimate"]),
        )
        for row in evaluated
    )
    r_deltas = tuple(
        cast(
            Decimal,
            _decimal_or_none(row["delta_net_r_estimate"]),
        )
        for row in evaluated
    )
    total_pnl = sum(pnl_deltas, ZERO)
    total_r = sum(r_deltas, ZERO)
    leave_one_trade_pnl = tuple(
        total_pnl - value for value in pnl_deltas
    )
    leave_one_trade_r = tuple(
        total_r - value for value in r_deltas
    )

    by_market_pnl: dict[str, Decimal] = {}
    by_market_r: dict[str, Decimal] = {}
    for row, pnl_delta, r_delta in zip(
        evaluated,
        pnl_deltas,
        r_deltas,
        strict=True,
    ):
        market = cast(str, row["market"])
        by_market_pnl[market] = (
            by_market_pnl.get(market, ZERO) + pnl_delta
        )
        by_market_r[market] = (
            by_market_r.get(market, ZERO) + r_delta
        )
    leave_one_market_pnl = tuple(
        total_pnl - value for value in by_market_pnl.values()
    )
    leave_one_market_r = tuple(
        total_r - value for value in by_market_r.values()
    )

    return {
        "evaluated_trades": len(evaluated),
        "market_count": len(by_market_pnl),
        "delta_net_pnl": str(total_pnl),
        "delta_net_r": str(total_r),
        "economics_positive": (
            total_pnl > ZERO and total_r > ZERO
        ),
        "leave_one_trade_out_min_delta_pnl": str(
            min(leave_one_trade_pnl, default=ZERO)
        ),
        "leave_one_trade_out_min_delta_r": str(
            min(leave_one_trade_r, default=ZERO)
        ),
        "positive_after_removing_any_one_trade": (
            len(evaluated) >= 2
            and min(leave_one_trade_pnl, default=ZERO) > ZERO
            and min(leave_one_trade_r, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_delta_pnl": str(
            min(leave_one_market_pnl, default=ZERO)
        ),
        "leave_one_market_out_min_delta_r": str(
            min(leave_one_market_r, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(by_market_pnl) >= 2
            and min(leave_one_market_pnl, default=ZERO) > ZERO
            and min(leave_one_market_r, default=ZERO) > ZERO
        ),
    }


def _digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def _state_metadata(
    raw_state: Mapping[str, object],
) -> dict[str, object]:
    if raw_state.get("schema_version") != (
        EXECUTION_SHADOW_STATE_SCHEMA_VERSION
    ):
        raise ProfitLockExecutionLedgerError(
            "unsupported execution-shadow state schema"
        )
    started_at_ms = _nonnegative_int(
        raw_state,
        "started_at_ms",
    )
    execution_config = raw_state.get("execution_config")
    if not isinstance(execution_config, dict):
        raise ProfitLockExecutionLedgerError(
            "execution_config must be an object"
        )
    rules = raw_state.get("rules")
    if rules != _expected_rules():
        raise ProfitLockExecutionLedgerError(
            "execution-shadow rule/config candidate drift"
        )
    return {
        "state_schema_version": (
            EXECUTION_SHADOW_STATE_SCHEMA_VERSION
        ),
        "started_at_ms": started_at_ms,
        "execution_config": execution_config,
        "rules": rules,
    }


def _reconcile_journal(
    rows: tuple[dict[str, object], ...],
    trades: Sequence[TradeJournalEntry],
    *,
    started_at_ms: int,
) -> None:
    trade_by_id = {trade.trade_id: trade for trade in trades}
    if len(trade_by_id) != len(tuple(trades)):
        raise ProfitLockExecutionLedgerError(
            "journal contains duplicate trade ids"
        )
    for row in rows:
        trade_id = cast(str, row["trade_id"])
        trade = trade_by_id.get(trade_id)
        if trade is None:
            raise ProfitLockExecutionLedgerError(
                "execution-shadow outcome has no journal trade"
            )
        expected = {
            "opening_plan_id": trade.opening_plan_id,
            "market": trade.market.canonical,
            "direction": trade.direction.value,
            "actual_net_pnl": str(trade.net_pnl),
            "actual_net_r": str(trade.net_r),
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise ProfitLockExecutionLedgerError(
                    f"execution-shadow outcome journal drift: {key}"
                )
        if trade.opened_at_ms < started_at_ms:
            raise ProfitLockExecutionLedgerError(
                "execution-shadow outcome predates frozen start"
            )


def validate_profit_lock_execution_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger kind is unsupported"
        )
    if raw.get("research_only") is not True:
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger must be research-only"
        )
    if raw.get("execution_authority") is not False:
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger cannot execute"
        )
    if raw.get("promotion_authority") is not False:
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger cannot promote"
        )
    metadata = raw.get("candidate")
    if not isinstance(metadata, dict):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution candidate metadata is invalid"
        )
    if metadata.get("state_schema_version") != (
        EXECUTION_SHADOW_STATE_SCHEMA_VERSION
    ):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution state schema drift"
        )
    if not isinstance(metadata.get("started_at_ms"), int):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution start is invalid"
        )
    if not isinstance(metadata.get("execution_config"), dict):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution config is invalid"
        )
    if metadata.get("rules") != _expected_rules():
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution rules drift"
        )

    rows = _canonical_rows(raw.get("rows"))
    if raw.get("row_count") != len(rows):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution row digest mismatch"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution source history must be a list"
        )
    if not isinstance(raw.get("summary"), dict):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution summary must be an object"
        )
    if not isinstance(raw.get("readiness"), dict):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution readiness must be an object"
        )
    if not isinstance(raw.get("economic_robustness"), dict):
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution economics must be an object"
        )
    expected_digest = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_digest:
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_profit_lock_execution_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfitLockExecutionLedgerError(
            "profit-lock execution ledger file is invalid"
        ) from exc
    return validate_profit_lock_execution_ledger(raw)


def update_profit_lock_execution_ledger(
    trades: Sequence[TradeJournalEntry],
    raw_state: Mapping[str, object],
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

    candidate = _state_metadata(raw_state)
    rows = _canonical_rows(raw_state.get("outcomes"))
    started_at_ms = cast(int, candidate["started_at_ms"])
    _reconcile_journal(
        rows,
        trades,
        started_at_ms=started_at_ms,
    )

    excluded_closed_trades = _nonnegative_int(
        raw_state,
        "excluded_closed_trades",
    )
    lineage_mismatch_closed_trades = _nonnegative_int(
        raw_state,
        "lineage_mismatch_closed_trades",
    )
    orphaned_restored_positions = _nonnegative_int(
        raw_state,
        "orphaned_restored_positions",
    )
    rule_ids = tuple(
        rule.rule_id for rule in DEFAULT_PROFIT_LOCK_RULES
    )
    rule_summaries = tuple(
        _rule_summary(rows, rule_id) for rule_id in rule_ids
    )
    readiness = _readiness_payload(
        rule_summaries,
        lineage_mismatch_closed_trades=(
            lineage_mismatch_closed_trades
        ),
        orphaned_restored_positions=orphaned_restored_positions,
    )
    economics = {
        rule_id: _economic_robustness(rows, rule_id)
        for rule_id in rule_ids
    }

    previous_rows: tuple[dict[str, object], ...] = ()
    source_history: list[object] = []
    prior_ledger_sha256: str | None = None
    previous_counters = {
        "excluded_closed_trades": 0,
        "lineage_mismatch_closed_trades": 0,
        "orphaned_restored_positions": 0,
    }
    if previous is not None:
        validated = validate_profit_lock_execution_ledger(previous)
        if validated.get("candidate") != candidate:
            raise ProfitLockExecutionLedgerError(
                "profit-lock execution candidate metadata drift"
            )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProfitLockExecutionLedgerError(
                "profit-lock execution source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProfitLockExecutionLedgerError(
                    "profit-lock execution source history entry is invalid"
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
                    raise ProfitLockExecutionLedgerError(
                        "duplicate source artifact identity drift"
                    )
                return validated

        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        current_by_identity = {
            _row_identity(row): row for row in rows
        }
        for old in previous_rows:
            current = current_by_identity.get(_row_identity(old))
            if current is None:
                raise ProfitLockExecutionLedgerError(
                    "previous profit-lock outcome disappeared"
                )
            if current != old:
                raise ProfitLockExecutionLedgerError(
                    "previous profit-lock outcome changed"
                )
        source_history = list(raw_history)
        prior_ledger_sha256 = cast(
            str,
            validated["ledger_sha256"],
        )
        prior_integrity = validated.get("integrity_counters")
        if not isinstance(prior_integrity, dict):
            raise ProfitLockExecutionLedgerError(
                "prior integrity counters are invalid"
            )
        for key in previous_counters:
            value = prior_integrity.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ProfitLockExecutionLedgerError(
                    "prior integrity counter is invalid"
                )
            previous_counters[key] = value

    current_counters = {
        "excluded_closed_trades": excluded_closed_trades,
        "lineage_mismatch_closed_trades": (
            lineage_mismatch_closed_trades
        ),
        "orphaned_restored_positions": (
            orphaned_restored_positions
        ),
    }
    for key, prior in previous_counters.items():
        if current_counters[key] < prior:
            raise ProfitLockExecutionLedgerError(
                f"profit-lock execution counter regressed: {key}"
            )

    old_identities = {
        _row_identity(row) for row in previous_rows
    }
    new_rows = tuple(
        row for row in rows if _row_identity(row) not in old_identities
    )
    source_history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "artifact_name": source_artifact_name,
            "artifact_digest": source_artifact_digest,
            "row_count": len(rows),
            "new_row_count": len(new_rows),
            "rows_sha256": _rows_sha256(rows),
        }
    )

    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate": candidate,
        "integrity_counters": current_counters,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "rows_sha256": _rows_sha256(rows),
        "source_history": source_history,
        "summary": {
            "closed_outcome_count": len(rows),
            "rules": list(rule_summaries),
        },
        "readiness": readiness,
        "economic_robustness": economics,
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
