"""Read-only after-cost net-edge study of a completed PAPER trade journal.

This CLI is NOT an execution command or an original source authentication
certificate. It neither changes nor silently copies baseline cash custody.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.journal.store import JournalConsistencyError, JournalStore
from cocomelon.research.prospective_net_edge_admission import (
    ProspectiveNetEdgeState,
    replay_net_floor_on_original_closes,
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_without_sqlite_sidecars(source: Path) -> None:
    if not source.is_file():
        raise ValueError("original PAPER journal file missing")
    for name in (
        source.name + "-wal",
        source.name + "-shm",
        source.name + "-journal",
    ):
        if (source.parent / name).exists():
            raise ValueError(
                "PAPER journal is not a sealed standalone snapshot: "
                "SQLite WAL/SHM or rollback sidecar present"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "RESEARCH ONLY: replay frozen net-R admission against exact "
            "completed baseline PAPER journal without mutating account state."
        ),
    )
    parser.add_argument("journal_sqlite", type=Path)
    parser.add_argument("--freeze-ms", type=int, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    options = parser.parse_args(argv)
    source = options.journal_sqlite
    dest = options.json_out
    if source.resolve() == dest.resolve():
        parser.error("output cannot overwrite original PAPER journal")
    try:
        state = ProspectiveNetEdgeState(frozen_at_ms=options.freeze_ms)
        _snapshot_without_sqlite_sidecars(source)
        digest_before = _digest(source)
        journal = JournalStore(source, read_only=True)
        try:
            integrity = journal.connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()
            if integrity != ("ok",):
                raise JournalConsistencyError(
                    "original journal SQLite integrity check failed"
                )
            baseline = tuple(journal.iter_trades())
        finally:
            journal.close()
        _snapshot_without_sqlite_sidecars(source)
        digest_after = _digest(source)
        if digest_before != digest_after:
            raise JournalConsistencyError(
                "original journal changed during research evaluation"
            )
        result = replay_net_floor_on_original_closes(
            baseline, state=state,
        )
    except (OSError, ValueError, JournalConsistencyError) as exc:
        parser.error(str(exc))
    result.update({
        "local_original_journal_sha256": digest_before,
        "local_original_journal_trade_count": len(baseline),
        "local_journal_schema_and_trade_ids_verified": True,
        # A local filesystem digest does not prove the GitHub Action
        # artifact was authentic, that all original market data arrived,
        # or that a capital-matched new PAPER account made real money.
        "independent_signed_source_authentication_verified": False,
        "all_source_gaps_closed_and_72h_verified": False,
        "capital_matched_challenger_account_verified": False,
        "positive_absolute_after_cost_marked_equity_verified": False,
        "executed_on_real_market": False,
        "execution_authority": False,
        "promotion_authority": False,
    })
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Never silently overwrite an earlier future-cohort verdict.
    try:
        with dest.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except FileExistsError:
        parser.error("research verdict already exists; refusing overwrite")
    print(json.dumps({
        "original_closed_trades": len(baseline),
        "prospective_evaluated_trades": result["forward_original_rows"],
        "prospective_admitted_trades": result["forward_original_admitted"],
        "promotion_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
