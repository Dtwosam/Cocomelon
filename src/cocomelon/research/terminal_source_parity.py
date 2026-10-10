"""Read-only parity audit of an immutable accepted ledger against a later source.

The ledger remains authoritative only as *historical published evidence*.
Never replace its terminal rows, drop losses, or infer execution/promotion
authority from matching or nonmatching historical reconstructions.

This module reports only opaque identity hashes, field paths, and counts.
Raw market, trade, opportunity, PnL, and feature values are not disclosed.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Final

from cocomelon.research.prospective_risk_rejected_forward_markout_ledger import (
    validate_risk_rejected_forward_markout_ledger,
)
from cocomelon.research.terminal_row_drift import (
    MAX_DRIFT_PATHS,
    changed_field_paths,
)

MAX_RECEIPTS: Final = 12


class TerminalSourceParityError(RuntimeError):
    """A source input is not safe to compare with an immutable ledger."""


def _fingerprint(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _require_source_rows(source: object) -> tuple[dict[str, object], ...]:
    if not isinstance(source, dict):
        raise TerminalSourceParityError("source summary must be an object")
    if (
        source.get("research_only") is not True
        or source.get("execution_authority") is not False
        or source.get("promotion_authority") is not False
    ):
        raise TerminalSourceParityError("source authority is invalid")
    rows = source.get("risk_rejected_rows")
    evaluated = source.get("risk_rejected_stack_evaluated")
    if (
        not isinstance(rows, list)
        or isinstance(evaluated, bool)
        or not isinstance(evaluated, int)
        or evaluated != len(rows)
    ):
        raise TerminalSourceParityError("source risk-rejected row count is invalid")
    seen: set[str] = set()
    verified: list[dict[str, object]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise TerminalSourceParityError("source contains invalid row")
        identity = raw.get("opportunity_id")
        if not isinstance(identity, str) or not identity:
            raise TerminalSourceParityError("source contains invalid identity")
        if identity in seen:
            raise TerminalSourceParityError("source repeats an opportunity identity")
        seen.add(identity)
        verified.append(raw)
    return tuple(verified)


def audit_terminal_source_parity(
    previous_ledger: object,
    rebuilt_source: object,
    *,
    receipt_limit: int = MAX_RECEIPTS,
) -> dict[str, object]:
    """Compare all historically published terminal fields without modifying them.

    A positive row match is descriptive only; never enough to promote a
    strategy. Historical mismatches and missing original rows always block
    parity, including when economic/markout fields have not changed.
    """
    if (
        isinstance(receipt_limit, bool)
        or not isinstance(receipt_limit, int)
        or receipt_limit < 1
        or receipt_limit > MAX_RECEIPTS
    ):
        raise TerminalSourceParityError("receipt limit must be between 1 and 12")
    previous = validate_risk_rejected_forward_markout_ledger(previous_ledger)
    source_rows = _require_source_rows(rebuilt_source)
    assert isinstance(rebuilt_source, dict)
    old_rows = previous["rows"]
    if not isinstance(old_rows, tuple):
        raise TerminalSourceParityError("validated ledger rows must be immutable")
    source_by_id = {row["opportunity_id"]: row for row in source_rows}
    changed = 0
    unchanged = 0
    missing = 0
    markout_changed = 0
    classification_only = 0
    pointer_counts: Counter[str] = Counter()
    receipts: list[dict[str, object]] = []
    missing_fingerprints: list[str] = []

    for old_row in old_rows:
        if not isinstance(old_row, dict):
            raise TerminalSourceParityError("validated ledger contains invalid row")
        identity = old_row.get("opportunity_id")
        if not isinstance(identity, str) or not identity:
            raise TerminalSourceParityError("validated ledger identity is invalid")
        current = source_by_id.get(identity)
        if current is None:
            missing += 1
            if len(missing_fingerprints) < receipt_limit:
                missing_fingerprints.append(_fingerprint(identity))
            continue
        # Project only already sealed row fields: later research diagnostics
        # are permitted as NEW fields but never allowed to alter sealed ones.
        projection = {
            field: current[field]
            for field in old_row
            if field in current
        }
        if projection == old_row:
            unchanged += 1
            continue
        changed += 1
        pointers = changed_field_paths(
            old_row, projection, limit=MAX_DRIFT_PATHS + 1
        )
        # Never miss a price-outcome rewrite just because there were
        # more than 12 earlier classification fields in a bounded receipt.
        changed_economics = old_row.get("markouts") != projection.get("markouts")
        if changed_economics:
            markout_changed += 1
        else:
            classification_only += 1
        for path in pointers[:MAX_DRIFT_PATHS]:
            pointer_counts[path] += 1
        if len(receipts) < receipt_limit:
            receipts.append(
                {
                    "opportunity_sha256_prefix": _fingerprint(identity),
                    "changed_json_pointers": list(pointers[:MAX_DRIFT_PATHS]),
                    "drift_paths_truncated": len(pointers) > MAX_DRIFT_PATHS,
                    "markout_drift": changed_economics,
                }
            )

    causal_exposures = rebuilt_source.get(
        "risk_rejected_journal_future_close_exposure_opportunities"
    )
    causal_instrumented = (
        rebuilt_source.get("journal_asof_provenance")
        == "closed_trades_only_no_original_open_event_witness"
        and isinstance(causal_exposures, int)
        and not isinstance(causal_exposures, bool)
        and causal_exposures >= 0
    )
    if causal_exposures is not None and not causal_instrumented:
        raise TerminalSourceParityError("causal journal exposure metadata is invalid")
    integrity_clean = rebuilt_source.get("risk_rejected_integrity_clean")
    if not isinstance(integrity_clean, bool):
        raise TerminalSourceParityError("risk-rejected integrity status is missing")
    history = previous.get("source_history")
    assert isinstance(history, list)
    previous_integrity_clean = bool(history) and all(
        isinstance(item, dict) and item.get("integrity_clean") is True
        for item in history
    )
    historical_parity = changed == 0 and missing == 0
    return {
        "kind": "terminal-source-parity-redacted-audit-v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_candidate_readiness": False,
        "source_rows": len(source_rows),
        "previous_terminal_rows": len(old_rows),
        "previous_rows_unchanged": unchanged,
        "previous_rows_changed": changed,
        "previous_rows_missing": missing,
        "changed_rows_markout_drift": markout_changed,
        "changed_rows_classification_only": classification_only,
        "changed_field_counts": dict(sorted(pointer_counts.items())),
        "drift_receipts": receipts,
        "missing_opportunity_sha256_prefixes": missing_fingerprints,
        "receipts_truncated": changed > receipt_limit,
        "missing_receipts_truncated": missing > receipt_limit,
        "source_causal_asof_instrumented": causal_instrumented,
        "source_future_finalized_open_exposures": (
            causal_exposures if causal_instrumented else None
        ),
        "source_integrity_clean": integrity_clean,
        "previous_ledger_integrity_clean": previous_integrity_clean,
        "diagnostic_only": True,
        "research_readiness_grant": False,
        "historical_terminal_parity": historical_parity,
        "historical_parity_blocked": not historical_parity,
        "research_readiness_blocked": (
            not historical_parity
            or not integrity_clean
            or not previous_integrity_clean
            or not causal_instrumented
            or bool(causal_exposures)
        ),
        "accepted_ledger_sha256": previous["ledger_sha256"],
        "source_content_sha256": hashlib.sha256(
            json.dumps(
                rebuilt_source,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
