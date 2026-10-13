"""Read-only fail-closed terminal account-to-signed-checkpoint parity.

Never roll later SQLite states back or claim intervening fills as signed PnL.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from cocomelon.research.loss_context_paired_portfolio_shadow import _state_digest
from cocomelon.research.loss_context_paired_shadow_review import review_ledger_receipt
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    both_side_trend_matched_shadow_v2_freeze,
)

ROOT: Final = "both-side-trend-paired-shadow-v1"
SUMMARY: Final = "both-side-trend-paired-shadow-summary.json"
MAX_STATE_BYTES: Final = 64_000_000


class TerminalResearchSnapshotError(ValueError):
    """The exact archived paired accounts cannot be signed as one state."""


def _json_mapping(path: Path) -> dict[str, object]:
    if not path.is_file() or not (0 < path.stat().st_size <= MAX_STATE_BYTES):
        raise TerminalResearchSnapshotError(f"missing or unbounded {path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TerminalResearchSnapshotError(f"invalid JSON object {path.name}")
    return payload


def verify_terminal_snapshot(
    state_root: Path, *, root_name: str = ROOT, summary_name: str = SUMMARY,
) -> dict[str, object]:
    """Validate source arithmetic provenance, never independent feed or profit."""
    result: dict[str, object] = {
        "status": "unverified",
        "reasons": [],
        "signed_state_digest_verified": False,
        "signed_ledger_receipt_verified": False,
        "frozen_v2_candidate_identity_verified": False,
        "summary_checkpoint_matches_signed_state": False,
        "terminal_account_ids_match_signed_checkpoint": False,
        "signed_record_count": None,
        "signed_checkpoint_count": None,
        "signed_last_record_ms": None,
        "lanes": None,
        "original_mainnet_feed_authenticated": False,
        "forward_after_cost_edge_verified": False,
        "paper_only": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    try:
        if (root_name, summary_name) not in (
            (ROOT, SUMMARY),
            (
                "both-side-trend-paired-shadow-v2",
                "both-side-trend-paired-shadow-v2-summary.json",
            ),
        ):
            raise TerminalResearchSnapshotError("unknown paired campaign identity")
        folder = state_root / root_name
        state = _json_mapping(folder / "paired-shadow-state.json")
        summary = _json_mapping(state_root / summary_name)
        result["campaign_state_root"] = root_name
        unsigned = dict(state)
        digest = unsigned.pop("state_digest", None)
        if not isinstance(digest, str) or digest != _state_digest(unsigned):
            raise TerminalResearchSnapshotError("paired signed state digest mismatch")
        if (
            state.get("schema_version") != 2
            or state.get("handoff_safe") is not True
            or state.get("paper_only") is not True
            or state.get("research_only") is not True
            or state.get("execution_authority") is not False
            or state.get("promotion_authority") is not False
        ):
            raise TerminalResearchSnapshotError("signed paired state authority invalid")
        result["signed_state_digest_verified"] = True
        if root_name == "both-side-trend-paired-shadow-v2":
            expected_v2 = both_side_trend_matched_shadow_v2_freeze()
            on_disk_v2 = verify_loss_context_portfolio_shadow_freeze(
                state_root / "both-side-trend-paired-shadow-v2-freeze.json"
            )
            if (
                on_disk_v2 != expected_v2
                or state.get("portfolio_shadow_candidate_id") != expected_v2.candidate_id
            ):
                raise TerminalResearchSnapshotError(
                    "v2 state candidate identity does not match sealed v2 freeze"
                )
            result["frozen_v2_candidate_identity_verified"] = True
        candidate = state.get("portfolio_shadow_candidate_id")
        if not isinstance(candidate, str) or not candidate:
            raise TerminalResearchSnapshotError("signed trial candidate ID missing")
        receipt = review_ledger_receipt(
            folder / "review-ledger.jsonl", candidate_id=candidate,
        )
        if (
            receipt.get("row_count") != state.get("review_ledger_row_count")
            or receipt.get("latest_row_digest")
            != state.get("review_ledger_latest_row_digest")
        ):
            raise TerminalResearchSnapshotError("signed review ledger receipt mismatch")
        result["signed_ledger_receipt_verified"] = True
        result["signed_checkpoint_count"] = receipt.get("row_count")
        result["signed_record_count"] = state.get("record_count")
        result["signed_last_record_ms"] = state.get("last_record_available_at_ms")
        if (
            summary.get("checkpoint_published") is not True
            or summary.get("checkpoint_error") is not None
            or summary.get("checkpoint") != state
        ):
            raise TerminalResearchSnapshotError(
                "published trend summary not equal to durable signed state"
            )
        result["summary_checkpoint_matches_signed_state"] = True
        last = result["signed_last_record_ms"]
        if type(last) is not int or last < 0:
            raise TerminalResearchSnapshotError("invalid last signed event timestamp")
        lanes: dict[str, object] = {}
        for name in ("baseline", "candidate"):
            signed_lane = state.get(name)
            if not isinstance(signed_lane, dict):
                raise TerminalResearchSnapshotError(f"{name} signed lane absent")
            signed_id = signed_lane.get("account_state_id")
            if not isinstance(signed_id, str) or not signed_id:
                raise TerminalResearchSnapshotError(f"{name} signed account ID absent")
            database = folder / f"{name}-execution.sqlite3"
            if not database.is_file():
                raise TerminalResearchSnapshotError(f"{name} SQLite account absent")
            with sqlite3.connect(
                f"{database.as_uri()}?mode=ro", uri=True,
            ) as conn:
                conn.execute("PRAGMA query_only=ON")
                row = conn.execute(
                    "SELECT state_id,payload_json FROM paper_account_state "
                    "WHERE singleton_id=1"
                ).fetchone()
            if row is None or not isinstance(row[0], str):
                raise TerminalResearchSnapshotError(f"{name} SQLite state absent")
            account = json.loads(row[1])
            if not isinstance(account, dict):
                raise TerminalResearchSnapshotError(f"{name} account JSON invalid")
            current_ms = account.get("updated_at_ms")
            if type(current_ms) is not int or current_ms < 0:
                raise TerminalResearchSnapshotError(f"{name} SQLite timestamp invalid")
            lanes[name] = {
                "signed_account_id": signed_id,
                "sqlite_account_id": row[0],
                "matches": signed_id == row[0],
                "sqlite_updated_at_ms": current_ms,
                "sqlite_minus_signed_record_ms": current_ms - last,
            }
        result["lanes"] = lanes
        if not all(lane["matches"] for lane in lanes.values()):
            result["status"] = "terminal_account_checkpoint_diverged"
            result["reasons"] = [
                "signed_account_ids_not_preserved_in_terminal_sqlite"
            ]
            return result
        result["terminal_account_ids_match_signed_checkpoint"] = True
        result["status"] = "terminal_source_account_snapshot_coherent"
        result["reasons"] = [
            "account_id_parity_is_not_venue_authentication_or_profit"
        ]
    except (
        OSError, ValueError, RuntimeError, TypeError, KeyError,
        sqlite3.DatabaseError,
    ) as exc:
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root-name", default=ROOT)
    parser.add_argument("--summary-name", default=SUMMARY)
    args = parser.parse_args(argv)
    payload = verify_terminal_snapshot(
        args.state_root, root_name=args.root_name, summary_name=args.summary_name,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(
        f".{args.output.name}.{os.getpid()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps(payload, sort_keys=True))
    # Optional research failure never stops paper or exact-state successor.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
