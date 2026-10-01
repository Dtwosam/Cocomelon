from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotError,
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_momentum_band_entry import (
    EMBARGO_MS,
    MAX_SIGNED_DAY_RETURN,
    MIN_SIGNED_RETURN_1H,
    ProspectiveMomentumBandEntryState,
    prospective_momentum_band_entry_summary,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-momentum-band-entry-ledger-v1"
ZERO: Final = Decimal("0")


class ProspectiveMomentumBandEntryLedgerError(RuntimeError):
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


def _required_string(
    raw: dict[str, object],
    key: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveMomentumBandEntryLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(
    raw: dict[str, object],
    key: str,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveMomentumBandEntryLedgerError(
            f"{key} must be an integer"
        )
    return value


def _decimal_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveMomentumBandEntryLedgerError(
            f"{field} must be a string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveMomentumBandEntryLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveMomentumBandEntryLedgerError(
            f"{field} must be finite"
        )
    return value


def _optional_decimal_string(
    value: object,
    *,
    field: str,
) -> str | None:
    if value is None:
        return None
    return _decimal_string(value, field=field)


def _optional_sha256(
    value: object,
    *,
    field: str,
) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ProspectiveMomentumBandEntryLedgerError(
            f"{field} must be lowercase SHA-256 or null"
        )
    return value


def _row_identity(
    row: dict[str, object],
) -> tuple[int, str]:
    return (
        cast(int, row["opened_at_ms"]),
        cast(str, row["opening_plan_id"]),
    )


def _canonical_row(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveMomentumBandEntryLedgerError(
            "ledger row must be an object"
        )

    trade_id = _required_string(raw, "trade_id")
    opening_plan_id = _required_string(raw, "opening_plan_id")
    feature_snapshot_id = _required_string(raw, "feature_snapshot_id")
    if (
        len(feature_snapshot_id) != 24
        or any(
            char not in "0123456789abcdef"
            for char in feature_snapshot_id
        )
    ):
        raise ProspectiveMomentumBandEntryLedgerError(
            "feature_snapshot_id must be lowercase 24-character hex"
        )
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveMomentumBandEntryLedgerError(
            "ledger row direction must be long or short"
        )
    opened_at_ms = _required_int(raw, "opened_at_ms")
    closed_at_ms = _required_int(raw, "closed_at_ms")
    if opened_at_ms < 0 or closed_at_ms < opened_at_ms:
        raise ProspectiveMomentumBandEntryLedgerError(
            "ledger row timestamps are invalid"
        )
    exit_reason = _required_string(raw, "exit_reason")
    net_pnl = _decimal_string(raw.get("net_pnl"), field="net_pnl")
    net_r = _decimal_string(raw.get("net_r"), field="net_r")
    prior_strikes = _required_int(raw, "prior_strikes")
    if prior_strikes < 0:
        raise ProspectiveMomentumBandEntryLedgerError(
            "prior_strikes must be non-negative"
        )

    decision = _required_string(raw, "decision")
    if decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate decision must be ADMIT or BLOCK"
        )
    reason = _required_string(raw, "reason")
    feature_status = _required_string(raw, "feature_status")
    if feature_status not in {
        "complete",
        "incomplete",
        "missing",
        "not_evaluated_nonzero_strike",
    }:
        raise ProspectiveMomentumBandEntryLedgerError(
            "feature_status is unsupported"
        )
    feature_record_sha256 = _optional_sha256(
        raw.get("feature_record_sha256"),
        field="feature_record_sha256",
    )
    signed_return_1h = _optional_decimal_string(
        raw.get("signed_return_1h"),
        field="signed_return_1h",
    )
    signed_day_return = _optional_decimal_string(
        raw.get("signed_day_return"),
        field="signed_day_return",
    )
    candidate_admitted = raw.get("candidate_admitted")
    if not isinstance(candidate_admitted, bool):
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate_admitted must be boolean"
        )
    if candidate_admitted != (decision == "ADMIT"):
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate admission does not match decision"
        )

    if reason == "nonzero_strike_bypass":
        if (
            prior_strikes <= 0
            or not candidate_admitted
            or feature_status != "not_evaluated_nonzero_strike"
            or feature_record_sha256 is not None
            or signed_return_1h is not None
            or signed_day_return is not None
        ):
            raise ProspectiveMomentumBandEntryLedgerError(
                "nonzero-strike bypass row is inconsistent"
            )
    elif reason == "missing_feature_fail_open":
        if (
            prior_strikes != 0
            or not candidate_admitted
            or feature_status != "missing"
            or feature_record_sha256 is not None
            or signed_return_1h is not None
            or signed_day_return is not None
        ):
            raise ProspectiveMomentumBandEntryLedgerError(
                "missing-feature row is inconsistent"
            )
    elif reason == "incomplete_feature_fail_open":
        if (
            prior_strikes != 0
            or not candidate_admitted
            or feature_status != "incomplete"
            or feature_record_sha256 is None
            or signed_return_1h is not None
            or signed_day_return is not None
        ):
            raise ProspectiveMomentumBandEntryLedgerError(
                "incomplete-feature row is inconsistent"
            )
    elif reason in {"momentum_band", "momentum_band_pass"}:
        if (
            prior_strikes != 0
            or feature_status != "complete"
            or feature_record_sha256 is None
            or signed_return_1h is None
            or signed_day_return is None
        ):
            raise ProspectiveMomentumBandEntryLedgerError(
                "complete momentum row is inconsistent"
            )
        should_block = (
            Decimal(signed_return_1h) < MIN_SIGNED_RETURN_1H
            or Decimal(signed_day_return) > MAX_SIGNED_DAY_RETURN
        )
        expected_reason = (
            "momentum_band" if should_block else "momentum_band_pass"
        )
        expected_decision = "BLOCK" if should_block else "ADMIT"
        if reason != expected_reason or decision != expected_decision:
            raise ProspectiveMomentumBandEntryLedgerError(
                "momentum decision does not match frozen thresholds"
            )
    else:
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate decision reason is unsupported"
        )

    return {
        "trade_id": trade_id,
        "opening_plan_id": opening_plan_id,
        "feature_snapshot_id": feature_snapshot_id,
        "feature_record_sha256": feature_record_sha256,
        "feature_status": feature_status,
        "market": market,
        "direction": direction,
        "opened_at_ms": opened_at_ms,
        "closed_at_ms": closed_at_ms,
        "exit_reason": exit_reason,
        "net_pnl": net_pnl,
        "net_r": net_r,
        "prior_strikes": prior_strikes,
        "decision": decision,
        "reason": reason,
        "signed_return_1h": signed_return_1h,
        "signed_day_return": signed_day_return,
        "candidate_admitted": candidate_admitted,
    }


def _canonical_rows(
    raw: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveMomentumBandEntryLedgerError(
            "ledger rows must be a list"
        )
    rows = tuple(_canonical_row(row) for row in raw)
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveMomentumBandEntryLedgerError(
            "duplicate ledger row identity"
        )
    trade_ids = tuple(cast(str, row["trade_id"]) for row in rows)
    if len(trade_ids) != len(set(trade_ids)):
        raise ProspectiveMomentumBandEntryLedgerError(
            "duplicate ledger trade id"
        )
    opening_plan_ids = tuple(
        cast(str, row["opening_plan_id"]) for row in rows
    )
    if len(opening_plan_ids) != len(set(opening_plan_ids)):
        raise ProspectiveMomentumBandEntryLedgerError(
            "duplicate ledger opening plan id"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def _candidate_rows(
    trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveMomentumBandEntryState,
) -> tuple[
    tuple[dict[str, object], ...],
    dict[str, object],
]:
    values = tuple(trades)
    summary = prospective_momentum_band_entry_summary(
        values,
        feature_store,
        state,
    )
    raw_strikes = summary.get("decision_prior_strikes")
    raw_details = summary.get("decision_details")
    if not isinstance(raw_strikes, dict) or not isinstance(
        raw_details,
        dict,
    ):
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate summary is missing decision evidence"
        )

    prospective = tuple(
        sorted(
            (
                trade
                for trade in values
                if trade.opened_at_ms >= state.started_at_ms
            ),
            key=lambda trade: (
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    rows: list[dict[str, object]] = []
    for trade in prospective:
        raw_prior = raw_strikes.get(trade.trade_id)
        raw_detail = raw_details.get(trade.trade_id)
        if isinstance(raw_prior, bool) or not isinstance(raw_prior, int):
            raise ProspectiveMomentumBandEntryLedgerError(
                "candidate summary is missing prior strikes"
            )
        if not isinstance(raw_detail, dict):
            raise ProspectiveMomentumBandEntryLedgerError(
                "candidate summary is missing trade detail"
            )
        if raw_detail.get("feature_snapshot_id") != trade.feature_snapshot_id:
            raise ProspectiveMomentumBandEntryLedgerError(
                "candidate detail feature identity mismatch"
            )
        decision = raw_detail.get("decision")
        reason = raw_detail.get("reason")
        if not isinstance(decision, str) or not isinstance(reason, str):
            raise ProspectiveMomentumBandEntryLedgerError(
                "candidate detail decision is invalid"
            )

        feature_status: str
        feature_record_sha256: str | None = None
        signed_return_1h: str | None = None
        signed_day_return: str | None = None
        if reason == "nonzero_strike_bypass":
            feature_status = "not_evaluated_nonzero_strike"
        elif reason == "missing_feature_fail_open":
            feature_status = "missing"
            if feature_store.load(trade.feature_snapshot_id) is not None:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "missing-feature decision has a stored feature"
                )
        elif reason == "incomplete_feature_fail_open":
            feature_status = "incomplete"
            verified = feature_store.load(trade.feature_snapshot_id)
            if verified is None:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "incomplete-feature decision lost its feature record"
                )
            feature_record_sha256 = verified.record_sha256
            snapshot = verified.snapshot
            if snapshot.return_1h is not None and snapshot.day_return is not None:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "incomplete-feature decision is now complete"
                )
        elif reason in {"momentum_band", "momentum_band_pass"}:
            feature_status = "complete"
            verified = feature_store.load(trade.feature_snapshot_id)
            if verified is None:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "evaluated feature record disappeared"
                )
            feature_record_sha256 = verified.record_sha256
            snapshot = verified.snapshot
            if snapshot.market != trade.market:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "evaluated feature market mismatch"
                )
            if snapshot.as_of_ms > trade.opened_at_ms:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "evaluated feature is from the future"
                )
            if snapshot.return_1h is None or snapshot.day_return is None:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "evaluated feature became incomplete"
                )
            signed_return_1h = raw_detail.get("signed_return_1h")
            signed_day_return = raw_detail.get("signed_day_return")
            if not isinstance(signed_return_1h, str) or not isinstance(
                signed_day_return,
                str,
            ):
                raise ProspectiveMomentumBandEntryLedgerError(
                    "evaluated signed momentum is missing"
                )
        else:
            raise ProspectiveMomentumBandEntryLedgerError(
                "candidate detail reason is unsupported"
            )

        rows.append(
            {
                "trade_id": trade.trade_id,
                "opening_plan_id": trade.opening_plan_id,
                "feature_snapshot_id": trade.feature_snapshot_id,
                "feature_record_sha256": feature_record_sha256,
                "feature_status": feature_status,
                "market": trade.market.canonical,
                "direction": trade.direction.value,
                "opened_at_ms": trade.opened_at_ms,
                "closed_at_ms": trade.closed_at_ms,
                "exit_reason": trade.exit_reason,
                "net_pnl": str(trade.net_pnl),
                "net_r": str(trade.net_r),
                "prior_strikes": raw_prior,
                "decision": decision,
                "reason": reason,
                "signed_return_1h": signed_return_1h,
                "signed_day_return": signed_day_return,
                "candidate_admitted": decision == "ADMIT",
            }
        )

    canonical = _canonical_rows(tuple(rows))
    if len(canonical) != summary.get("prospective_closed_trades"):
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate row count does not match summary"
        )
    admitted = sum(
        row["candidate_admitted"] is True for row in canonical
    )
    if admitted != summary.get("admitted_trades"):
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate admitted count does not match summary"
        )
    if len(canonical) - admitted != summary.get("blocked_trades"):
        raise ProspectiveMomentumBandEntryLedgerError(
            "candidate blocked count does not match summary"
        )
    return canonical, summary


def _summary_snapshot(
    summary: dict[str, object],
) -> dict[str, object]:
    keys = (
        "prospective_closed_trades",
        "admitted_trades",
        "blocked_trades",
        "blocked_wins",
        "blocked_losses",
        "blocked_net_pnl",
        "actual_net_pnl",
        "candidate_net_pnl",
        "delta_net_pnl",
        "actual_net_r",
        "candidate_net_r",
        "delta_net_r",
        "zero_strike_feature_evaluated",
        "nonzero_strike_bypass",
        "missing_feature_trades",
        "missing_feature_trade_ids",
        "by_direction",
        "blocked_by_market",
        "robustness",
        "readiness",
    )
    return {key: summary[key] for key in keys}


def validate_momentum_band_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger kind is unsupported"
        )

    candidate_id = _required_string(raw, "candidate_id")
    frozen_at_ms = _required_int(raw, "frozen_at_ms")
    started_at_ms = _required_int(raw, "started_at_ms")
    embargo_ms = _required_int(raw, "embargo_ms")
    if frozen_at_ms < 0:
        raise ProspectiveMomentumBandEntryLedgerError(
            "frozen_at_ms must be non-negative"
        )
    if embargo_ms != EMBARGO_MS:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger embargo drift"
        )
    if started_at_ms != frozen_at_ms + EMBARGO_MS:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger start does not match freeze"
        )
    try:
        expected = ProspectiveMomentumBandEntryState(
            frozen_at_ms=frozen_at_ms,
            candidate_id=candidate_id,
        )
    except ValueError as exc:
        raise ProspectiveMomentumBandEntryLedgerError(
            str(exc)
        ) from exc
    if raw.get("rule") != expected.payload()["rule"]:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger rule drift"
        )

    rows = _canonical_rows(raw.get("rows"))
    if raw.get("row_count") != len(rows):
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger row digest mismatch"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger source history must be a list"
        )
    summary = raw.get("summary")
    if not isinstance(summary, dict):
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger summary must be an object"
        )
    expected_digest = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_digest:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_momentum_band_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band ledger file is invalid"
        ) from exc
    return validate_momentum_band_ledger(raw)


def update_momentum_band_ledger(
    trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveMomentumBandEntryState,
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

    try:
        rows, candidate_summary = _candidate_rows(
            trades,
            feature_store,
            state,
        )
    except LearningFeatureSnapshotError as exc:
        raise ProspectiveMomentumBandEntryLedgerError(
            "momentum-band feature evidence is invalid"
        ) from exc
    summary = _summary_snapshot(candidate_summary)

    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_momentum_band_ledger(previous)
        for key, current in (
            ("candidate_id", state.candidate_id),
            ("frozen_at_ms", state.frozen_at_ms),
            ("started_at_ms", state.started_at_ms),
            ("embargo_ms", EMBARGO_MS),
            ("rule", state.payload()["rule"]),
        ):
            if validated.get(key) != current:
                raise ProspectiveMomentumBandEntryLedgerError(
                    f"momentum-band ledger metadata drift: {key}"
                )

        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveMomentumBandEntryLedgerError(
                "momentum-band ledger source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveMomentumBandEntryLedgerError(
                    "momentum-band ledger source history entry is invalid"
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
                    raise ProspectiveMomentumBandEntryLedgerError(
                        "duplicate source run artifact identity drift"
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
        current_by_opening_plan = {
            cast(str, row["opening_plan_id"]): row
            for row in rows
        }
        for old in previous_rows:
            opening_plan_id = cast(str, old["opening_plan_id"])
            current = current_by_opening_plan.get(opening_plan_id)
            if current is None:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "previous momentum-band opening row disappeared"
                )
            if current != old:
                raise ProspectiveMomentumBandEntryLedgerError(
                    "previous momentum-band trade row changed"
                )

    old_opening_plan_ids = {
        cast(str, row["opening_plan_id"])
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in rows
        if cast(str, row["opening_plan_id"])
        not in old_opening_plan_ids
    )
    history.append(
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
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "rule": state.payload()["rule"],
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "first_opened_at_ms": (
            None
            if not rows
            else min(
                cast(int, row["opened_at_ms"])
                for row in rows
            )
        ),
        "last_closed_at_ms": (
            None
            if not rows
            else max(
                cast(int, row["closed_at_ms"])
                for row in rows
            )
        ),
        "rows_sha256": _rows_sha256(rows),
        "source_history": history,
        "summary": summary,
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
