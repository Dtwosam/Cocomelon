"""Offline-only verification of a fresh v3 paired PAPER terminal account.

The state digest is self-consistency evidence, NOT an externally witnessed
signature. The original venue feed, source-gaps and 72h outcomes must still be
verified by a separate independent auditor before ANY economic claim.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from cocomelon.execution.store import (
    _account_from_payload,
    _account_payload,
    _canonical_json,
    _position_payload,
)
from cocomelon.research.loss_context_paired_portfolio_shadow import (
    _state_digest,
)


class V3AccountAuditError(ValueError):
    """An original v3 research terminal cash/account receipt is contradictory."""


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise V3AccountAuditError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _decimal(value: object, field: str) -> Decimal:
    if type(value) is not str:
        raise V3AccountAuditError(f"{field} must be an exact decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise V3AccountAuditError(f"{field} invalid decimal") from exc
    if not amount.is_finite():
        raise V3AccountAuditError(f"{field} nonfinite")
    return amount


def _summed_original_cash(conn: sqlite3.Connection, *, table: str, key: str) -> Decimal:
    total = Decimal("0")
    for (serialized,) in conn.execute(f"SELECT payload_json FROM {table}"):
        try:
            entry: object = json.loads(serialized)
        except (ValueError, TypeError) as exc:
            raise V3AccountAuditError(f"{table} journal is invalid") from exc
        payload = _mapping(entry, table)
        total += _decimal(payload.get(key), f"{table}.{key}")
    return total


def _read_lane(
    path: Path, *, lane: str, signed: dict[str, Any],
    reported: dict[str, Any], expected_start_cash: Decimal,
) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise V3AccountAuditError(f"{lane} original execution SQLite missing")
    try:
        conn = sqlite3.connect(
            path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True,
        )
        try:
            conn.execute("PRAGMA query_only = ON")
            if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise V3AccountAuditError(f"{lane} SQLite integrity not verified")
            state_rows = conn.execute(
                "SELECT state_id, payload_json FROM paper_account_state "
                "WHERE singleton_id=1"
            ).fetchall()
            if len(state_rows) != 1:
                raise V3AccountAuditError(f"{lane} account singleton missing")
            claimed_id, payload_json = state_rows[0]
            account_payload = _mapping(json.loads(payload_json), lane)
            reconstructed = _account_from_payload(account_payload)
            if (
                reconstructed.state_id != claimed_id
                or _canonical_json(_account_payload(reconstructed)) != payload_json
                or claimed_id != signed.get("account_state_id")
            ):
                raise V3AccountAuditError(
                    f"{lane} original SQLite account identity changed"
                )
            account = reconstructed
            # These SQL tables materialize actual positions and rolling peaks.
            positions = conn.execute(
                "SELECT market, position_id, payload_json "
                "FROM paper_positions ORDER BY market"
            ).fetchall()
            expected_positions = [
                (
                    pos.market.canonical, pos.position_id,
                    _canonical_json(_position_payload(pos)),
                )
                for pos in account.positions
            ]
            if positions != expected_positions:
                raise V3AccountAuditError(f"{lane} position journal differs")
            peaks = conn.execute(
                "SELECT timestamp_ms, equity FROM paper_rolling_peak_candidates "
                "ORDER BY ordinal"
            ).fetchall()
            if peaks != [
                (point.timestamp_ms, str(point.equity))
                for point in account.rolling_peak_candidates
            ]:
                raise V3AccountAuditError(f"{lane} peak equity journal differs")
            recorded_fees = _summed_original_cash(
                conn, table="paper_fills", key="taker_fee",
            )
            recorded_funding = _summed_original_cash(
                conn, table="paper_funding_events", key="cash_delta",
            )
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, V3AccountAuditError):
            raise
        raise V3AccountAuditError(
            f"{lane} original SQLite could not be verified"
        ) from exc

    def match(name: str, actual: Decimal) -> None:
        if _decimal(reported.get(name), f"{lane}.{name}") != actual:
            raise V3AccountAuditError(f"{lane} reported {name} does not match original")

    if account.starting_cash != expected_start_cash:
        raise V3AccountAuditError(f"{lane} initial capital mismatch")
    if account.cumulative_fees != recorded_fees:
        raise V3AccountAuditError(f"{lane} fill fee journal differs")
    if account.cumulative_funding != recorded_funding:
        raise V3AccountAuditError(f"{lane} funding cash journal differs")
    realized_after_cost = (
        account.realized_gross_pnl - account.cumulative_fees
        + account.cumulative_funding
    )
    if (
        account.cash != account.starting_cash + realized_after_cost
        or account.equity != account.cash + account.unrealized_pnl
        or account.available_margin != max(
            Decimal("0"), account.equity - account.reserved_margin,
        )
    ):
        raise V3AccountAuditError(f"{lane} whole-account cash does not reconcile")
    for field, value in (
        ("equity", account.equity),
        ("realized_net_pnl", realized_after_cost),
        ("total_account_pnl", account.equity - account.starting_cash),
        ("daily_realized_pnl", account.daily_realized_pnl),
        ("rolling_7d_peak_equity", account.rolling_7d_peak_equity),
        ("gross_open_notional", account.gross_open_notional),
        ("available_margin", account.available_margin),
    ):
        match(field, value)
    if (
        type(reported.get("open_position_count")) is not int
        or reported["open_position_count"] != len(account.positions)
    ):
        raise V3AccountAuditError(f"{lane} open positions differ")
    return {
        "state_id_matches_local_checkpoint": True,
        "positions_and_peak_journal_match": True,
        "fills_and_funding_cash_reconciled": True,
        "starting_cash_usd": str(account.starting_cash),
        "equity_usd": str(account.equity),
        "gross_realized_pnl_usd": str(account.realized_gross_pnl),
        "fill_fees_usd": str(recorded_fees),
        "funding_cash_usd": str(recorded_funding),
        "unrealized_pnl_usd": str(account.unrealized_pnl),
        "realized_after_cost_usd": str(realized_after_cost),
        "marked_after_cost_usd": str(account.equity - account.starting_cash),
        "open_position_count": len(account.positions),
        "full_account_economic_edge_certified": False,
    }


def audit_fresh_v3_paired_accounts(
    state_root: Path, *, checkpoint: dict[str, object],
    summary: dict[str, object], starting_cash: Decimal,
    expected_candidate_id: str, expected_record_count: int,
) -> dict[str, object]:
    """Match BOTH durable SQLite accounts, frozen checkpoint and report.

    Run only after the paired research actor has closed both SQLite stores.
    No path derived from state is ever followed; old v1/v2 accounts excluded.
    This verifies *local ledger coherence*, not external origin nor PnL edge.
    """
    if state_root.name in {
        "both-side-trend-paired-shadow-v1",
        "both-side-trend-paired-shadow-v2",
        "loss-context-paired-v5",
    } or type(expected_record_count) is not int or expected_record_count <= 0:
        raise V3AccountAuditError("v3 root or record bound not admissible")
    if not starting_cash.is_finite() or starting_cash <= 0:
        raise V3AccountAuditError("starting cash invalid")
    if (
        checkpoint.get("portfolio_shadow_candidate_id") != expected_candidate_id
        or summary.get("portfolio_shadow_candidate_id") != expected_candidate_id
        or checkpoint.get("research_only") is not True
        or checkpoint.get("execution_authority") is not False
        or checkpoint.get("promotion_authority") is not False
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or checkpoint.get("record_count") != expected_record_count
        or summary.get("record_count") != expected_record_count
        or summary.get("restored_from_checkpoint") is not False
        or checkpoint.get("handoff_safe") is not True
    ):
        raise V3AccountAuditError("v3 frozen original account identity invalid")
    actual_checkpoint_path = state_root / "paired-shadow-state.json"
    if not actual_checkpoint_path.is_file():
        raise V3AccountAuditError("v3 frozen checkpoint missing")
    try:
        disk_checkpoint = _mapping(
            json.loads(actual_checkpoint_path.read_text(encoding="utf-8")),
            "v3 checkpoint",
        )
    except (OSError, ValueError) as exc:
        raise V3AccountAuditError("v3 checkpoint unreadable") from exc
    unsigned = dict(disk_checkpoint)
    recorded_digest = unsigned.pop("state_digest", None)
    if (
        not isinstance(recorded_digest, str)
        or _state_digest(unsigned) != recorded_digest
        or disk_checkpoint != checkpoint
    ):
        raise V3AccountAuditError("v3 checkpoint digest or original bytes differ")

    lanes = {}
    for lane in ("baseline", "candidate"):
        lanes[lane] = _read_lane(
            state_root / f"{lane}-execution.sqlite3",
            lane=lane,
            signed=_mapping(disk_checkpoint.get(lane), f"{lane} signed"),
            reported=_mapping(summary.get(lane), f"{lane} summary"),
            expected_start_cash=starting_cash,
        )

    baseline = lanes["baseline"]
    candidate = lanes["candidate"]
    baseline_net = _decimal(baseline["marked_after_cost_usd"], "baseline marked")
    candidate_net = _decimal(candidate["marked_after_cost_usd"], "candidate marked")
    relative = candidate_net - baseline_net
    if (
        _decimal(summary.get("candidate_minus_baseline_total_account_pnl"), "relative")
        != relative
        or _decimal(summary.get("candidate_minus_baseline_equity"), "relative equity")
        != relative
    ):
        raise V3AccountAuditError("candidate-to-baseline equity delta falsified")
    return {
        "schema": "v3-readonly-original-paired-sqlite-cash-audit-v1",
        "local_checkpoint_self_digest_and_exact_accounts_reconciled": True,
        "baseline": baseline,
        "candidate": candidate,
        "candidate_minus_baseline_marked_after_cost_usd": str(relative),
        "candidate_marked_account_positive": candidate_net > 0,
        "baseline_marked_account_positive": baseline_net > 0,
        "both_accounts_positive": candidate_net > 0 and baseline_net > 0,
        "relative_candidate_advantage_positive": relative > 0,
        "original_source_venue_completeness_authenticated": False,
        "external_checkpoint_signature_verified": False,
        "72h_forward_profitability_certified": False,
        "study_promotable": False,
        "paper_only": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
