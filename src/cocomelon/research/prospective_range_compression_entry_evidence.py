from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_range_compression_entry import (
    MAX_RANGE_EXPANSION_15M,
    ProspectiveRangeCompressionEntryState,
    prospective_range_compression_entry_summary,
)

EVIDENCE_SCHEMA_VERSION: Final = 1
EVIDENCE_KIND: Final = "prospective-range-compression-entry-evidence-v1"


class ProspectiveRangeCompressionEvidenceError(RuntimeError):
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


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveRangeCompressionEvidenceError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveRangeCompressionEvidenceError(
            f"{key} must be an integer"
        )
    return value


def _decimal_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ProspectiveRangeCompressionEvidenceError(
            f"{field} must be a decimal string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveRangeCompressionEvidenceError(
            f"{field} must be a decimal string"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveRangeCompressionEvidenceError(
            f"{field} must be finite"
        )
    return value


def _optional_sha256(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ProspectiveRangeCompressionEvidenceError(
            f"{field} must be lowercase SHA-256 or null"
        )
    return value


def _source_digest(value: object) -> str:
    value = _required_string({"value": value}, "value")
    if not value.startswith("sha256:"):
        raise ProspectiveRangeCompressionEvidenceError(
            "source_artifact_digest must start with sha256:"
        )
    digest = value.removeprefix("sha256:")
    if (
        len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ProspectiveRangeCompressionEvidenceError(
            "source_artifact_digest must contain lowercase SHA-256"
        )
    return value


def _head_sha(value: object) -> str:
    value = _required_string({"value": value}, "value")
    if (
        len(value) != 40
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ProspectiveRangeCompressionEvidenceError(
            "source_head_sha must be lowercase 40-character git SHA"
        )
    return value


def _row_identity(row: dict[str, object]) -> tuple[int, int, str]:
    return (
        cast(int, row["opened_at_ms"]),
        cast(int, row["closed_at_ms"]),
        cast(str, row["trade_id"]),
    )


def _canonical_row(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveRangeCompressionEvidenceError(
            "evidence row must be an object"
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
        raise ProspectiveRangeCompressionEvidenceError(
            "feature_snapshot_id must be lowercase 24-character hex"
        )
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveRangeCompressionEvidenceError(
            "direction must be long or short"
        )
    opened_at_ms = _required_int(raw, "opened_at_ms")
    closed_at_ms = _required_int(raw, "closed_at_ms")
    if opened_at_ms < 0 or closed_at_ms < opened_at_ms:
        raise ProspectiveRangeCompressionEvidenceError(
            "trade timestamps are invalid"
        )
    exit_reason = _required_string(raw, "exit_reason")
    net_pnl = _decimal_string(raw.get("net_pnl"), field="net_pnl")
    net_r = _decimal_string(raw.get("net_r"), field="net_r")
    feature_status = _required_string(raw, "feature_status")
    if feature_status not in {"complete", "incomplete", "missing"}:
        raise ProspectiveRangeCompressionEvidenceError(
            "feature_status is unsupported"
        )
    feature_record_sha256 = _optional_sha256(
        raw.get("feature_record_sha256"),
        field="feature_record_sha256",
    )
    decision = _required_string(raw, "decision")
    reason = _required_string(raw, "reason")
    if decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveRangeCompressionEvidenceError(
            "decision must be ADMIT or BLOCK"
        )
    range_expansion_raw = raw.get("range_expansion_15m")
    range_expansion_15m = (
        None
        if range_expansion_raw is None
        else _decimal_string(
            range_expansion_raw,
            field="range_expansion_15m",
        )
    )

    if reason == "missing_feature_fail_open":
        if (
            decision != "ADMIT"
            or feature_status != "missing"
            or feature_record_sha256 is not None
            or range_expansion_15m is not None
        ):
            raise ProspectiveRangeCompressionEvidenceError(
                "missing-feature row is inconsistent"
            )
    elif reason == "incomplete_feature_fail_open":
        if (
            decision != "ADMIT"
            or feature_status != "incomplete"
            or feature_record_sha256 is None
            or range_expansion_15m is not None
        ):
            raise ProspectiveRangeCompressionEvidenceError(
                "incomplete-feature row is inconsistent"
            )
    elif reason in {"range_compression", "range_compression_pass"}:
        if (
            feature_status != "complete"
            or feature_record_sha256 is None
            or range_expansion_15m is None
        ):
            raise ProspectiveRangeCompressionEvidenceError(
                "complete range row is inconsistent"
            )
        should_block = (
            Decimal(range_expansion_15m) <= MAX_RANGE_EXPANSION_15M
        )
        expected_reason = (
            "range_compression"
            if should_block
            else "range_compression_pass"
        )
        expected_decision = "BLOCK" if should_block else "ADMIT"
        if reason != expected_reason or decision != expected_decision:
            raise ProspectiveRangeCompressionEvidenceError(
                "range decision does not match frozen threshold"
            )
    else:
        raise ProspectiveRangeCompressionEvidenceError(
            "range decision reason is unsupported"
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
        "decision": decision,
        "reason": reason,
        "range_expansion_15m": range_expansion_15m,
        "candidate_admitted": decision == "ADMIT",
    }


def _canonical_rows(raw: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveRangeCompressionEvidenceError(
            "rows must be a list"
        )
    rows = tuple(_canonical_row(row) for row in raw)
    trade_ids = tuple(cast(str, row["trade_id"]) for row in rows)
    if len(trade_ids) != len(set(trade_ids)):
        raise ProspectiveRangeCompressionEvidenceError(
            "duplicate trade id in evidence"
        )
    plan_ids = tuple(cast(str, row["opening_plan_id"]) for row in rows)
    if len(plan_ids) != len(set(plan_ids)):
        raise ProspectiveRangeCompressionEvidenceError(
            "duplicate opening plan id in evidence"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(rows: tuple[dict[str, object], ...]) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _summary_snapshot(summary: dict[str, object]) -> dict[str, object]:
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
        "feature_evaluated_trades",
        "missing_feature_trades",
        "missing_feature_trade_ids",
        "by_direction",
        "blocked_by_market",
        "robustness",
        "economic_readiness",
        "readiness",
    )
    return {key: summary[key] for key in keys}


def _source_entry(
    *,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_head_sha: str,
    source_artifact_name: str,
    source_artifact_digest: str,
) -> dict[str, object]:
    if source_paper_run_id <= 0 or source_paper_run_attempt <= 0:
        raise ProspectiveRangeCompressionEvidenceError(
            "source run identity must be positive"
        )
    if not source_artifact_name.strip():
        raise ProspectiveRangeCompressionEvidenceError(
            "source artifact name must not be empty"
        )
    return {
        "source_paper_run_id": source_paper_run_id,
        "source_paper_run_attempt": source_paper_run_attempt,
        "source_head_sha": _head_sha(source_head_sha),
        "source_artifact_name": source_artifact_name,
        "source_artifact_digest": _source_digest(
            source_artifact_digest
        ),
    }


def _canonical_source_history(
    raw: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveRangeCompressionEvidenceError(
            "source_history must be a list"
        )
    values: list[dict[str, object]] = []
    identities: set[tuple[int, int]] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ProspectiveRangeCompressionEvidenceError(
                "source history entry must be an object"
            )
        entry = _source_entry(
            source_paper_run_id=_required_int(
                item,
                "source_paper_run_id",
            ),
            source_paper_run_attempt=_required_int(
                item,
                "source_paper_run_attempt",
            ),
            source_head_sha=_required_string(
                item,
                "source_head_sha",
            ),
            source_artifact_name=_required_string(
                item,
                "source_artifact_name",
            ),
            source_artifact_digest=_required_string(
                item,
                "source_artifact_digest",
            ),
        )
        identity = (
            cast(int, entry["source_paper_run_id"]),
            cast(int, entry["source_paper_run_attempt"]),
        )
        if identity in identities:
            raise ProspectiveRangeCompressionEvidenceError(
                "duplicate source run identity"
            )
        identities.add(identity)
        values.append(entry)
    return tuple(values)


def _evidence_digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "evidence_sha256"
    }


def validate_range_compression_evidence(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveRangeCompressionEvidenceError(
            "range-compression evidence must be an object"
        )
    if raw.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ProspectiveRangeCompressionEvidenceError(
            "range-compression evidence schema is unsupported"
        )
    if raw.get("kind") != EVIDENCE_KIND:
        raise ProspectiveRangeCompressionEvidenceError(
            "range-compression evidence kind is unsupported"
        )
    state_payload = raw.get("state")
    try:
        state = ProspectiveRangeCompressionEntryState.from_payload(
            state_payload
        )
    except Exception as exc:
        raise ProspectiveRangeCompressionEvidenceError(
            "range-compression state is invalid"
        ) from exc

    if raw.get("candidate_id") != state.candidate_id:
        raise ProspectiveRangeCompressionEvidenceError(
            "candidate_id does not match frozen state"
        )

    rows = _canonical_rows(raw.get("rows"))
    if raw.get("row_count") != len(rows):
        raise ProspectiveRangeCompressionEvidenceError(
            "row_count does not match rows"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveRangeCompressionEvidenceError(
            "row digest mismatch"
        )
    previous_row_count = _required_int(raw, "previous_row_count")
    new_row_count = _required_int(raw, "new_row_count")
    if previous_row_count < 0 or previous_row_count > len(rows):
        raise ProspectiveRangeCompressionEvidenceError(
            "previous_row_count is invalid"
        )
    if new_row_count != len(rows) - previous_row_count:
        raise ProspectiveRangeCompressionEvidenceError(
            "new_row_count is invalid"
        )
    prior_evidence_sha256 = raw.get("prior_evidence_sha256")
    if prior_evidence_sha256 is not None:
        _optional_sha256(
            prior_evidence_sha256,
            field="prior_evidence_sha256",
        )
    source_history = _canonical_source_history(raw.get("source_history"))
    if not source_history:
        raise ProspectiveRangeCompressionEvidenceError(
            "source_history must not be empty"
        )
    summary = raw.get("summary")
    if not isinstance(summary, dict):
        raise ProspectiveRangeCompressionEvidenceError(
            "summary must be an object"
        )
    if summary.get("prospective_closed_trades") != len(rows):
        raise ProspectiveRangeCompressionEvidenceError(
            "summary trade count does not match rows"
        )
    admitted = sum(
        row["candidate_admitted"] is True for row in rows
    )
    if summary.get("admitted_trades") != admitted:
        raise ProspectiveRangeCompressionEvidenceError(
            "summary admitted count does not match rows"
        )
    if summary.get("blocked_trades") != len(rows) - admitted:
        raise ProspectiveRangeCompressionEvidenceError(
            "summary blocked count does not match rows"
        )
    blocked_rows = tuple(
        row for row in rows if row["candidate_admitted"] is False
    )
    actual_pnl = sum(
        (Decimal(cast(str, row["net_pnl"])) for row in rows),
        Decimal("0"),
    )
    candidate_pnl = sum(
        (
            Decimal(cast(str, row["net_pnl"]))
            for row in rows
            if row["candidate_admitted"] is True
        ),
        Decimal("0"),
    )
    blocked_pnl = sum(
        (
            Decimal(cast(str, row["net_pnl"]))
            for row in blocked_rows
        ),
        Decimal("0"),
    )
    actual_r = sum(
        (Decimal(cast(str, row["net_r"])) for row in rows),
        Decimal("0"),
    )
    candidate_r = sum(
        (
            Decimal(cast(str, row["net_r"]))
            for row in rows
            if row["candidate_admitted"] is True
        ),
        Decimal("0"),
    )
    numeric_expectations = {
        "blocked_net_pnl": blocked_pnl,
        "actual_net_pnl": actual_pnl,
        "candidate_net_pnl": candidate_pnl,
        "delta_net_pnl": candidate_pnl - actual_pnl,
        "actual_net_r": actual_r,
        "candidate_net_r": candidate_r,
        "delta_net_r": candidate_r - actual_r,
    }
    for key, expected in numeric_expectations.items():
        raw_value = summary.get(key)
        if not isinstance(raw_value, str):
            raise ProspectiveRangeCompressionEvidenceError(
                f"summary {key} must be a decimal string"
            )
        try:
            observed = Decimal(raw_value)
        except InvalidOperation as exc:
            raise ProspectiveRangeCompressionEvidenceError(
                f"summary {key} must be a decimal string"
            ) from exc
        if not observed.is_finite() or observed != expected:
            raise ProspectiveRangeCompressionEvidenceError(
                f"summary {key} does not match rows"
            )
    blocked_wins = sum(
        Decimal(cast(str, row["net_pnl"])) > 0
        for row in blocked_rows
    )
    blocked_losses = sum(
        Decimal(cast(str, row["net_pnl"])) < 0
        for row in blocked_rows
    )
    if summary.get("blocked_wins") != blocked_wins:
        raise ProspectiveRangeCompressionEvidenceError(
            "summary blocked wins do not match rows"
        )
    if summary.get("blocked_losses") != blocked_losses:
        raise ProspectiveRangeCompressionEvidenceError(
            "summary blocked losses do not match rows"
        )
    feature_evaluated = sum(
        row["feature_status"] == "complete" for row in rows
    )
    if summary.get("feature_evaluated_trades") != feature_evaluated:
        raise ProspectiveRangeCompressionEvidenceError(
            "summary feature count does not match rows"
        )
    if summary.get("missing_feature_trades") != len(rows) - feature_evaluated:
        raise ProspectiveRangeCompressionEvidenceError(
            "summary missing feature count does not match rows"
        )

    canonical: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "candidate_id": state.candidate_id,
        "state": state.payload(),
        "row_count": len(rows),
        "previous_row_count": previous_row_count,
        "new_row_count": new_row_count,
        "rows_sha256": _rows_sha256(rows),
        "prior_evidence_sha256": prior_evidence_sha256,
        "source_history": list(source_history),
        "rows": list(rows),
        "summary": summary,
    }
    expected_digest = _sha256_text(
        _canonical_json(_evidence_digest_payload(canonical))
    )
    if raw.get("evidence_sha256") != expected_digest:
        raise ProspectiveRangeCompressionEvidenceError(
            "evidence digest mismatch"
        )
    canonical["evidence_sha256"] = expected_digest
    return canonical


def load_range_compression_evidence(
    path: Path,
) -> dict[str, object]:
    return validate_range_compression_evidence(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _candidate_rows(
    trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveRangeCompressionEntryState,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    values = tuple(trades)
    summary = prospective_range_compression_entry_summary(
        values,
        feature_store,
        state,
    )
    details = summary.get("decision_details")
    if not isinstance(details, dict):
        raise ProspectiveRangeCompressionEvidenceError(
            "candidate summary is missing decision details"
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
        detail = details.get(trade.trade_id)
        if not isinstance(detail, dict):
            raise ProspectiveRangeCompressionEvidenceError(
                "candidate summary is missing trade detail"
            )
        if detail.get("feature_snapshot_id") != trade.feature_snapshot_id:
            raise ProspectiveRangeCompressionEvidenceError(
                "candidate feature identity mismatch"
            )
        decision = detail.get("decision")
        reason = detail.get("reason")
        if not isinstance(decision, str) or not isinstance(reason, str):
            raise ProspectiveRangeCompressionEvidenceError(
                "candidate decision detail is invalid"
            )

        feature_status: str
        feature_record_sha256: str | None
        range_expansion_15m: str | None
        if reason == "missing_feature_fail_open":
            feature_status = "missing"
            feature_record_sha256 = None
            range_expansion_15m = None
            if feature_store.load(trade.feature_snapshot_id) is not None:
                raise ProspectiveRangeCompressionEvidenceError(
                    "missing feature decision has a stored feature"
                )
        elif reason == "incomplete_feature_fail_open":
            feature_status = "incomplete"
            verified = feature_store.load(trade.feature_snapshot_id)
            if verified is None:
                raise ProspectiveRangeCompressionEvidenceError(
                    "incomplete feature record disappeared"
                )
            feature_record_sha256 = verified.record_sha256
            if verified.snapshot.range_expansion_15m is not None:
                raise ProspectiveRangeCompressionEvidenceError(
                    "incomplete feature became complete"
                )
            range_expansion_15m = None
        elif reason in {
            "range_compression",
            "range_compression_pass",
        }:
            feature_status = "complete"
            verified = feature_store.load(trade.feature_snapshot_id)
            if verified is None:
                raise ProspectiveRangeCompressionEvidenceError(
                    "evaluated feature record disappeared"
                )
            snapshot = verified.snapshot
            if snapshot.market != trade.market:
                raise ProspectiveRangeCompressionEvidenceError(
                    "evaluated feature market mismatch"
                )
            if snapshot.as_of_ms > trade.opened_at_ms:
                raise ProspectiveRangeCompressionEvidenceError(
                    "evaluated feature is from the future"
                )
            if snapshot.range_expansion_15m is None:
                raise ProspectiveRangeCompressionEvidenceError(
                    "evaluated range feature became incomplete"
                )
            feature_record_sha256 = verified.record_sha256
            range_expansion_15m = detail.get("range_expansion_15m")
            if not isinstance(range_expansion_15m, str):
                raise ProspectiveRangeCompressionEvidenceError(
                    "candidate range value is missing"
                )
            if Decimal(range_expansion_15m) != snapshot.range_expansion_15m:
                raise ProspectiveRangeCompressionEvidenceError(
                    "candidate range value does not match feature"
                )
        else:
            raise ProspectiveRangeCompressionEvidenceError(
                "candidate decision reason is unsupported"
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
                "decision": decision,
                "reason": reason,
                "range_expansion_15m": range_expansion_15m,
                "candidate_admitted": decision == "ADMIT",
            }
        )
    canonical = _canonical_rows(rows)
    if len(canonical) != summary.get("prospective_closed_trades"):
        raise ProspectiveRangeCompressionEvidenceError(
            "candidate row count does not match summary"
        )
    return canonical, summary


def update_range_compression_evidence(
    trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveRangeCompressionEntryState,
    *,
    previous: dict[str, object] | None,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_head_sha: str,
    source_artifact_name: str,
    source_artifact_digest: str,
) -> dict[str, object]:
    rows, full_summary = _candidate_rows(
        trades,
        feature_store,
        state,
    )
    summary = _summary_snapshot(full_summary)
    source = _source_entry(
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_head_sha=source_head_sha,
        source_artifact_name=source_artifact_name,
        source_artifact_digest=source_artifact_digest,
    )

    prior_sha: str | None = None
    previous_rows: tuple[dict[str, object], ...] = ()
    source_history: list[dict[str, object]] = []
    if previous is not None:
        canonical_previous = validate_range_compression_evidence(
            previous
        )
        if canonical_previous["state"] != state.payload():
            raise ProspectiveRangeCompressionEvidenceError(
                "frozen candidate state drift"
            )
        previous_rows = _canonical_rows(
            canonical_previous["rows"]
        )
        previous_by_trade = {
            cast(str, row["trade_id"]): row
            for row in previous_rows
        }
        current_by_trade = {
            cast(str, row["trade_id"]): row
            for row in rows
        }
        missing = sorted(set(previous_by_trade) - set(current_by_trade))
        if missing:
            raise ProspectiveRangeCompressionEvidenceError(
                "prior evidence trade disappeared"
            )
        for trade_id, prior_row in previous_by_trade.items():
            if current_by_trade[trade_id] != prior_row:
                raise ProspectiveRangeCompressionEvidenceError(
                    f"prior evidence row drift: {trade_id}"
                )
        prior_sha = cast(str, canonical_previous["evidence_sha256"])
        source_history = list(
            cast(list[dict[str, object]], canonical_previous["source_history"])
        )
        for existing in source_history:
            if (
                existing["source_paper_run_id"]
                == source["source_paper_run_id"]
                and existing["source_paper_run_attempt"]
                == source["source_paper_run_attempt"]
            ):
                if existing != source:
                    raise ProspectiveRangeCompressionEvidenceError(
                        "duplicate source identity drift"
                    )
                if rows != previous_rows:
                    raise ProspectiveRangeCompressionEvidenceError(
                        "duplicate source changed evidence rows"
                    )
                return canonical_previous
        latest_source = source_history[-1]
        latest_identity = (
            cast(int, latest_source["source_paper_run_id"]),
            cast(int, latest_source["source_paper_run_attempt"]),
        )
        next_identity = (
            cast(int, source["source_paper_run_id"]),
            cast(int, source["source_paper_run_attempt"]),
        )
        if next_identity <= latest_identity:
            raise ProspectiveRangeCompressionEvidenceError(
                "source run identity regressed"
            )

    source_history.append(source)
    payload: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "candidate_id": state.candidate_id,
        "state": state.payload(),
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(rows) - len(previous_rows),
        "rows_sha256": _rows_sha256(rows),
        "prior_evidence_sha256": prior_sha,
        "source_history": source_history,
        "rows": list(rows),
        "summary": summary,
    }
    payload["evidence_sha256"] = _sha256_text(
        _canonical_json(_evidence_digest_payload(payload))
    )
    return validate_range_compression_evidence(payload)
