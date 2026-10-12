"""Read-only independent receipt for an archived both-side-trend paired paper handoff.

An outer ZIP matching GitHub artifact metadata is *not* a signed profitable
strategy. This audit independently binds original completed GitHub job steps,
the frozen candidate, both persistent execution stores, account-state digest,
and the append-only checkpoint ledger. No execution or promotion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from cocomelon.research.loss_context_paired_shadow_review import (
    build_paired_shadow_review,
    review_ledger_receipt,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    TRIAL_ID,
    both_side_trend_matched_shadow_freeze,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    TREND_PAIR_FREEZE_FILE,
    TREND_PAIR_STATE_ROOT,
    TREND_PAIR_SUMMARY_FILE,
)

SOURCE_WORKFLOW_PATH: Final = ".github/workflows/continuous-paper.yml"
ARTIFACT_PREFIX: Final = "continuous-paper-both-side-trend-paired-shadow-"
MAX_RECEIPT_MEMBER_BYTES: Final = 128 * 1024 * 1024
# Locked to the actual frozen paper execution schema. Schema migrations need
# their own independent verifier; never silently accept unexpected formats.
EXPECTED_PAPER_SCHEMA_VERSION: Final = "1"
REQUIRED_PAPER_TABLES: Final = frozenset({
    "paper_meta", "paper_order_plans", "paper_execution_attempts",
    "paper_fills", "paper_positions", "paper_position_events",
    "paper_funding_events", "paper_account_state",
    "paper_rolling_peak_candidates",
})


class TrendPairHandoffAuditError(RuntimeError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise TrendPairHandoffAuditError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _json_file(path: Path) -> dict[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), path.name)


def _signed_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _source_class(
    *,
    run: dict[str, object],
    jobs: dict[str, object],
    repository: str,
    run_id: int,
    attempt: int,
) -> str:
    if (
        run.get("id") != run_id
        or run.get("run_attempt") != attempt
        or run.get("path") != SOURCE_WORKFLOW_PATH
        or run.get("head_branch") != "main"
        or run.get("status") != "completed"
    ):
        raise TrendPairHandoffAuditError("source worker identity is not exact")
    source_repository = _mapping(run.get("repository"), "repository")
    if source_repository.get("full_name") != repository:
        raise TrendPairHandoffAuditError("source repository identity mismatch")
    if run.get("event") not in ("push", "workflow_dispatch"):
        raise TrendPairHandoffAuditError(
            "source worker event is not a recognized original paper trigger"
        )
    source_head = run.get("head_sha")
    if (
        not isinstance(source_head, str) or len(source_head) != 40
        or any(char not in "0123456789abcdef" for char in source_head)
    ):
        raise TrendPairHandoffAuditError("source worker commit is invalid")

    raw_jobs = jobs.get("jobs")
    if not isinstance(raw_jobs, list):
        raise TrendPairHandoffAuditError("source jobs missing")
    confirmed_paper_jobs = 0
    for item in raw_jobs:
        job = _mapping(item, "worker job")
        if job.get("run_id") != run_id:
            raise TrendPairHandoffAuditError("foreign source job in job list")
        # Do not combine a successful upload on one attempt with a trading
        # step from an older run attempt after a rerun.
        if job.get("run_attempt") != attempt or job.get("name") != "paper":
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            raise TrendPairHandoffAuditError("paper worker step history absent")
        successful_steps = {
            step["name"]
            for step in steps
            if isinstance(step, dict)
            and step.get("conclusion") == "success"
            and isinstance(step.get("name"), str)
        }
        if {
            "Run continuous paper trader",
            "Upload isolated both-side trend paired-paper evidence",
        } <= successful_steps:
            confirmed_paper_jobs += 1
    if confirmed_paper_jobs != 1:
        raise TrendPairHandoffAuditError(
            "exact attempt original trading and trend artifact upload not both proven"
        )
    if run.get("conclusion") == "success":
        return "completed_successful_worker"
    return "completed_non_success_worker"


def _validate_artifact(
    artifacts: dict[str, object],
    archive: Path,
    *,
    run_id: int,
    attempt: int,
) -> str:
    raw = artifacts.get("artifacts")
    if not isinstance(raw, list):
        raise TrendPairHandoffAuditError("GitHub artifacts list missing")
    name = f"{ARTIFACT_PREFIX}{run_id}-{attempt}"
    exact = [
        _mapping(item, "source artifact") for item in raw
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(exact) != 1:
        raise TrendPairHandoffAuditError(
            "missing or ambiguous exact original trend paired artifact"
        )
    artifact = exact[0]
    if artifact.get("expired") is True:
        raise TrendPairHandoffAuditError("source trend artifact expired")
    if not archive.is_file():
        raise TrendPairHandoffAuditError("source trend artifact ZIP not downloaded")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    actual = digest.hexdigest()
    if artifact.get("digest") != f"sha256:{actual}":
        raise TrendPairHandoffAuditError(
            "source artifact outer ZIP SHA256 mismatch"
        )
    return actual


def _member(archive: zipfile.ZipFile, filename: str) -> bytes:
    allowed = {filename, f"continuous-paper-state/{filename}"}
    matching = [
        info for info in archive.infolist() if info.filename in allowed
    ]
    if len(matching) != 1:
        raise TrendPairHandoffAuditError(
            f"missing or ambiguous independent paired member: {filename}"
        )
    info = matching[0]
    if info.is_dir() or info.file_size > MAX_RECEIPT_MEMBER_BYTES:
        raise TrendPairHandoffAuditError("paired member is not a bounded file")
    return archive.read(info)


def _verify_archived_execution_store(
    archive: zipfile.ZipFile, work: Path, *, lane: str,
) -> None:
    """Check structural integrity; do not mutate stores or infer signed PnL.

    A SQLite header alone cannot prove the store is valid: reject corrupt
    pages, missing execution schema, and unexpected schema versions.
    This is not a fill/account replay or independent market authentication.
    """
    if lane not in ("baseline", "candidate"):
        raise TrendPairHandoffAuditError("invalid paired execution lane")
    name = f"{TREND_PAIR_STATE_ROOT}/{lane}-execution.sqlite3"
    matching = [
        info for info in archive.infolist()
        if info.filename in {name, f"continuous-paper-state/{name}"}
    ]
    if len(matching) != 1 or matching[0].is_dir():
        raise TrendPairHandoffAuditError(
            f"paired {lane} execution store absent or ambiguous"
        )
    info = matching[0]
    if info.file_size <= 0 or info.file_size > MAX_RECEIPT_MEMBER_BYTES:
        raise TrendPairHandoffAuditError(
            f"paired {lane} execution store size invalid"
        )
    path = work / f"{lane}-execution.sqlite3"
    extracted = 0
    with archive.open(info) as source, path.open("xb") as destination:
        while chunk := source.read(1024 * 1024):
            extracted += len(chunk)
            if extracted > MAX_RECEIPT_MEMBER_BYTES:
                raise TrendPairHandoffAuditError(
                    f"paired {lane} execution store exceeds size bound"
                )
            destination.write(chunk)
    if extracted != info.file_size:
        raise TrendPairHandoffAuditError(
            f"paired {lane} execution store length mismatch"
        )
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise TrendPairHandoffAuditError(
                f"paired {lane} SQLite quick_check failed"
            )
        tables = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not REQUIRED_PAPER_TABLES.issubset(tables):
            raise TrendPairHandoffAuditError(
                f"paired {lane} execution store missing paper schema tables"
            )
        version = conn.execute(
            "SELECT value FROM paper_meta WHERE key='schema_version'"
        ).fetchone()
        if version is None or str(version[0]) != EXPECTED_PAPER_SCHEMA_VERSION:
            raise TrendPairHandoffAuditError(
                f"paired {lane} execution store schema version mismatch"
            )
    except sqlite3.DatabaseError as exc:
        raise TrendPairHandoffAuditError(
            f"paired {lane} execution store unreadable: {exc}"
        ) from exc
    finally:
        if conn is not None:
            conn.close()


_PNL_TOLERANCE: Final = Decimal("0.00000001")


def _amount(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except ArithmeticError as exc:
        raise TrendPairHandoffAuditError(
            "paired execution monetary value is invalid"
        ) from exc
    if not result.is_finite():
        raise ValueError("paired execution monetary value is not finite")
    return result


def _same_amount(actual: object, expected: object, field: str) -> None:
    if abs(_amount(actual) - _amount(expected)) > _PNL_TOLERANCE:
        raise TrendPairHandoffAuditError(
            f"paired execution economics mismatch: {field}"
        )


def _reconcile_archived_lane_economics(
    path: Path, *, account_state_id: str, ledger_lane: dict[str, object],
) -> dict[str, object]:
    """Independently reconstruct paired paper cashflows from archived fills.

    Read-only, with no market-feed authentication. Intentionally fail closed
    for unsupported overlapping opening positions rather than invent a trade.
    """
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        row = conn.execute(
            "SELECT state_id, payload_json FROM paper_account_state "
            "WHERE singleton_id=1"
        ).fetchone()
        if row is None or row[0] != account_state_id:
            raise TrendPairHandoffAuditError("paired account state identity mismatch")
        account = _mapping(json.loads(row[1]), "paired execution account")

        plans = {
            plan_id: _mapping(json.loads(raw), "execution plan")
            for plan_id, raw in conn.execute(
                "SELECT plan_id, payload_json FROM paper_order_plans"
            )
        }
        attempts: list[tuple[str, str, dict[str, object]]] = []
        for attempt_id, plan_id, raw in conn.execute(
            "SELECT attempt_id, plan_id, payload_json "
            "FROM paper_execution_attempts"
        ):
            attempt = _mapping(json.loads(raw), "execution attempt")
            if attempt.get("plan_id") != plan_id or plan_id not in plans:
                raise TrendPairHandoffAuditError("paired attempt plan lineage mismatch")
            attempts.append((attempt_id, plan_id, attempt))

        by_attempt: dict[str, list[dict[str, object]]] = {
            attempt_id: [] for attempt_id, _, _ in attempts
        }
        opening_fills = 0
        for _, attempt_id, plan_id, raw in conn.execute(
            "SELECT fill_id, attempt_id, plan_id, payload_json FROM paper_fills"
        ):
            fill = _mapping(json.loads(raw), "execution fill")
            if (
                attempt_id not in by_attempt
                or fill.get("attempt_id") != attempt_id
                or fill.get("plan_id") != plan_id
                or plan_id not in plans
            ):
                raise TrendPairHandoffAuditError("paired fill lineage mismatch")
            qty, price = _amount(fill.get("quantity")), _amount(fill.get("price"))
            if qty <= 0 or price <= 0 or _amount(fill.get("taker_fee")) < 0:
                raise TrendPairHandoffAuditError("paired execution fill invalid")
            _same_amount(fill.get("notional"), qty * price, "fill notional")
            by_attempt[attempt_id].append(fill)
            if plans[plan_id].get("reduce_only") is False:
                opening_fills += 1

        for attempt_id, _, attempt in attempts:
            fills = by_attempt[attempt_id]
            qty = sum((_amount(f["quantity"]) for f in fills), Decimal(0))
            notional = sum((_amount(f["notional"]) for f in fills), Decimal(0))
            fees = sum((_amount(f["taker_fee"]) for f in fills), Decimal(0))
            _same_amount(attempt.get("filled_quantity"), qty, "filled quantity")
            _same_amount(attempt.get("gross_fill_notional"), notional, "fill notional sum")
            _same_amount(attempt.get("fee"), fees, "fill fee sum")
            _same_amount(
                attempt.get("requested_quantity"),
                _amount(attempt.get("unfilled_quantity")) + qty,
                "requested versus filled quantity",
            )
            if qty > 0:
                _same_amount(
                    attempt.get("average_fill_price"),
                    notional / qty,
                    "weighted average fill price",
                )
            elif attempt.get("average_fill_price") is not None:
                raise TrendPairHandoffAuditError("unfilled attempt has a price")

        funding: list[dict[str, object]] = []
        for _accrual_id, market, boundary_ms, position_id, raw in conn.execute(
            "SELECT accrual_id, market, boundary_ms, position_id, payload_json "
            "FROM paper_funding_events"
        ):
            event = _mapping(json.loads(raw), "funding event")
            if (
                event.get("market") != market
                or event.get("boundary_ms") != boundary_ms
                or event.get("position_id") != position_id
            ):
                raise TrendPairHandoffAuditError("paired funding lineage mismatch")
            funding.append(event)

        realized_gross = Decimal(0)
        fee_total = Decimal(0)
        funding_total = sum(
            (_amount(event["cash_delta"]) for event in funding), Decimal(0)
        )
        closed_count = 0
        side_counts = {"long": 0, "short": 0}
        side_net = {"long": Decimal(0), "short": Decimal(0)}
        active: dict[str, dict[str, object]] = {}
        for _, plan_id, attempt in sorted(
            attempts,
            key=lambda row: (
                row[2]["attempt_timestamp_ms"], row[0],
            ),
        ):
            fee_total += _amount(attempt["fee"])
            qty = _amount(attempt["filled_quantity"])
            if qty < 0 or _amount(attempt["fee"]) < 0:
                raise TrendPairHandoffAuditError(
                    "paired execution negative attempt quantity or fee"
                )
            if qty == 0:
                continue
            plan = plans[plan_id]
            market = str(plan["market"])
            price = _amount(attempt["average_fill_price"])
            fee = _amount(attempt["fee"])
            if plan.get("reduce_only") is False:
                if market in active:
                    raise TrendPairHandoffAuditError(
                        "overlapping opening positions not independently replayable"
                    )
                active[market] = {
                    "side": plan["side"], "remaining": qty, "price": price,
                    "entry_fee": fee, "exit_fee": Decimal(0),
                    "gross": Decimal(0),
                    "started": attempt["attempt_timestamp_ms"],
                }
            elif plan.get("reduce_only") is True:
                position = active.get(market)
                if (
                    position is None
                    or plan["side"] == position["side"]
                    or qty > position["remaining"]
                ):
                    raise TrendPairHandoffAuditError(
                        "paired reduce-only fill does not match an open position"
                    )
                direction = (
                    Decimal(1) if position["side"] == "buy" else Decimal(-1)
                )
                gross = qty * (price - position["price"]) * direction
                realized_gross += gross
                position["gross"] += gross
                position["exit_fee"] += fee
                position["remaining"] -= qty
                if position["remaining"] == 0:
                    matched_funding = sum(
                        (
                            _amount(event["cash_delta"]) for event in funding
                            if event["market"] == market
                            and position["started"] <= event["boundary_ms"]
                            <= attempt["attempt_timestamp_ms"]
                        ),
                        Decimal(0),
                    )
                    side = "long" if position["side"] == "buy" else "short"
                    side_net[side] += (
                        position["gross"] - position["entry_fee"]
                        - position["exit_fee"] + matched_funding
                    )
                    side_counts[side] += 1
                    closed_count += 1
                    del active[market]
            else:
                raise TrendPairHandoffAuditError("invalid reduce_only flag")

        stored_positions = account.get("positions")
        if not isinstance(stored_positions, list) or len(stored_positions) != len(active):
            raise TrendPairHandoffAuditError("paired open position count mismatch")
        for raw in stored_positions:
            position = _mapping(raw, "paired open position")
            tracked = active.get(str(position.get("market")))
            if tracked is None:
                raise TrendPairHandoffAuditError("paired open market mismatch")
            _same_amount(position["quantity"], tracked["remaining"], "open quantity")
            _same_amount(
                position["average_entry_price"], tracked["price"], "entry price"
            )
            expected_side = "long" if tracked["side"] == "buy" else "short"
            if position.get("side") != expected_side:
                raise TrendPairHandoffAuditError("paired open direction mismatch")
        materialized = {
            market: json.loads(raw)
            for market, raw in conn.execute(
                "SELECT market, payload_json FROM paper_positions"
            )
        }
        if materialized != {p["market"]: p for p in stored_positions}:
            raise TrendPairHandoffAuditError(
                "paired materialized open position mismatch"
            )
        _same_amount(account["realized_gross_pnl"], realized_gross, "gross PnL")
        _same_amount(account["cumulative_fees"], fee_total, "fee conservation")
        _same_amount(account["cumulative_funding"], funding_total, "funding conservation")
        _same_amount(
            account["cash"],
            _amount(account["starting_cash"]) + realized_gross
            - fee_total + funding_total,
            "cash conservation",
        )
        _same_amount(
            account["equity"],
            _amount(account["cash"]) + _amount(account["unrealized_pnl"]),
            "equity conservation",
        )
        _same_amount(ledger_lane["equity"], account["equity"], "signed ledger equity")
        _same_amount(
            ledger_lane["realized_net_pnl"],
            realized_gross - fee_total + funding_total,
            "signed realized net PnL",
        )
        _same_amount(
            ledger_lane["total_account_pnl"],
            _amount(account["equity"]) - _amount(account["starting_cash"]),
            "signed total account PnL",
        )
        for side in ("long", "short"):
            _same_amount(
                ledger_lane[f"{side}_closed_net_pnl"],
                side_net[side],
                f"signed {side} closed net PnL",
            )
            if ledger_lane[f"{side}_closed_trade_count"] != side_counts[side]:
                raise TrendPairHandoffAuditError("directional close count mismatch")
        if (
            ledger_lane.get("closed_trade_count") != closed_count
            or ledger_lane.get("open_position_count") != len(active)
            or ledger_lane.get("opening_fills") != opening_fills
            or ledger_lane.get("opening_execution_attempts") != sum(
                plans[plan_id].get("reduce_only") is False
                for _, plan_id, _ in attempts
            )
        ):
            raise TrendPairHandoffAuditError(
                "paired execution activity counts do not match signed ledger"
            )
        return {
            "closed_trades_from_fills": closed_count,
            "realized_gross_from_fills": str(realized_gross),
            "fees_from_fills": str(fee_total),
            "funding_from_events": str(funding_total),
            "realized_net_from_fills": str(
                realized_gross - fee_total + funding_total
            ),
            "equity_from_signed_account": account["equity"],
        }


def _extract_receipts(
    archive_path: Path,
    work: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], Path]:
    freeze_path = work / TREND_PAIR_FREEZE_FILE
    ledger_path = work / "review-ledger.jsonl"
    with zipfile.ZipFile(archive_path) as archive:
        freeze_path.write_bytes(_member(archive, TREND_PAIR_FREEZE_FILE))
        summary = _mapping(
            json.loads(_member(archive, TREND_PAIR_SUMMARY_FILE)),
            "trend paired summary",
        )
        state = _mapping(
            json.loads(_member(
                archive, f"{TREND_PAIR_STATE_ROOT}/paired-shadow-state.json",
            )),
            "trend paired state",
        )
        ledger_path.write_bytes(_member(
            archive, f"{TREND_PAIR_STATE_ROOT}/review-ledger.jsonl",
        ))
        for lane in ("baseline", "candidate"):
            _verify_archived_execution_store(archive, work, lane=lane)
    freeze = verify_loss_context_portfolio_shadow_freeze(freeze_path)
    if freeze != both_side_trend_matched_shadow_freeze():
        raise TrendPairHandoffAuditError("signed freeze != predeclared trend hypothesis")
    return freeze.to_dict(), summary, state, ledger_path


def audit_trend_handoff(
    *,
    run: dict[str, object],
    jobs: dict[str, object],
    artifacts: dict[str, object],
    archive: Path,
    repository: str,
    source_run_id: int,
    source_attempt: int,
) -> dict[str, object]:
    expected = both_side_trend_matched_shadow_freeze()
    result: dict[str, object] = {
        "trial_id": TRIAL_ID,
        "source_run_id": source_run_id,
        "source_run_attempt": source_attempt,
        "expected_candidate_id": expected.candidate_id,
        "source_class": "unverified",
        "status": "unverified",
        "reasons": [],
        "archive_sha256": None,
        "review_report": None,
        "independent_mainnet_market_source_authenticated": False,
        "durable_execution_sqlite_replay_verified": False,
        "archived_execution_sqlite_integrity_verified": False,
        "archived_execution_economics_reconciled": False,
        "reconciled_lanes": None,
        "full_forward_after_cost_profit_verified": False,
        "ready_for_review": False,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
        "promotion_authority": False,
        "execution_authority": False,
    }
    try:
        source_class = _source_class(
            run=run, jobs=jobs, repository=repository,
            run_id=source_run_id, attempt=source_attempt,
        )
        result["source_class"] = source_class
        digest = _validate_artifact(
            artifacts, archive,
            run_id=source_run_id, attempt=source_attempt,
        )
        result["archive_sha256"] = digest
        with tempfile.TemporaryDirectory() as directory:
            freeze, summary, state, ledger_path = _extract_receipts(
                archive, Path(directory),
            )
            result["archived_execution_sqlite_integrity_verified"] = True
            if freeze["candidate_id"] != expected.candidate_id:
                raise TrendPairHandoffAuditError("candidate ID mismatch")
            if summary.get("trial_id") != TRIAL_ID:
                raise TrendPairHandoffAuditError("trend paired trial identity drift")
            if summary.get("checkpoint_published") is not True:
                raise TrendPairHandoffAuditError("paired checkpoint unpublished")
            if summary.get("checkpoint_error") is not None:
                raise TrendPairHandoffAuditError("paired checkpoint reported error")
            if summary.get("checkpoint") != state:
                raise TrendPairHandoffAuditError("summary/checkpoint/state mismatch")
            if summary.get("frozen_forward_not_before_ms") != (
                expected.prospective_not_before_ms
            ):
                raise TrendPairHandoffAuditError("prospective boundary drift")
            for field in ("research_only", "shadow_only", "paper_only"):
                if summary.get(field) is not True or state.get(field) is not True:
                    raise TrendPairHandoffAuditError(
                        "paired research-only authority contract missing"
                    )
            for field in ("promotion_authority", "execution_authority"):
                if summary.get(field) is not False or state.get(field) is not False:
                    raise TrendPairHandoffAuditError(
                        "paired receipt granted prohibited authority"
                    )
            if (
                summary.get("forward_profitable_signed_account_edge_proven")
                is not False
                or summary.get("original_mainnet_source_and_gaps_independently_authenticated")
                is not False
            ):
                raise TrendPairHandoffAuditError(
                    "paired research-only source claims economic authority"
                )
            if state.get("portfolio_shadow_candidate_id") != expected.candidate_id:
                raise TrendPairHandoffAuditError("paired durable candidate mismatch")
            unsigned = dict(state)
            digest_value = unsigned.pop("state_digest", None)
            if digest_value != _signed_digest(unsigned):
                raise TrendPairHandoffAuditError("paired durable digest mismatch")
            ledger = review_ledger_receipt(
                ledger_path, candidate_id=expected.candidate_id,
            )
            if (
                state.get("review_ledger_row_count") != ledger["row_count"]
                or state.get("review_ledger_latest_row_digest")
                != ledger["latest_row_digest"]
            ):
                raise TrendPairHandoffAuditError("paired ledger receipt mismatch")
            # Replay the *stored* executions independently of the review
            # builder, and bind their accounts to the last signed ledger row.
            lines = ledger_path.read_text(encoding="utf-8").splitlines()
            if not lines:
                raise TrendPairHandoffAuditError("paired review ledger is empty")
            latest = _mapping(json.loads(lines[-1]), "latest signed paired row")
            reconciled: dict[str, object] = {}
            for lane in ("baseline", "candidate"):
                lane_state = _mapping(state.get(lane), f"{lane} state")
                lane_ledger = _mapping(latest.get(lane), f"{lane} ledger")
                state_id = lane_state.get("account_state_id")
                if not isinstance(state_id, str) or not state_id:
                    raise TrendPairHandoffAuditError(
                        f"{lane} durable account state ID absent"
                    )
                reconciled[lane] = _reconcile_archived_lane_economics(
                    Path(directory) / f"{lane}-execution.sqlite3",
                    account_state_id=state_id, ledger_lane=lane_ledger,
                )
            result["reconciled_lanes"] = reconciled
            result["archived_execution_economics_reconciled"] = True
            review = build_paired_shadow_review(expected, ledger_path)
            result["review_report"] = review
            result["record_count"] = state.get("record_count")
            result["verified_checkpoint_count"] = ledger["row_count"]
            result["status"] = "archive_checkpoint_lineage_verified"
            if source_class != "completed_successful_worker":
                result["reasons"] = [
                    "source_worker_was_not_fully_successful",
                ]
            elif review.get("ready_for_review") is not True:
                result["reasons"] = ["economic_review_not_ready"]
            else:
                result["reasons"] = [
                    "independent_mainnet_market_source_not_authenticated",
                ]
    except (
        OSError, ValueError, RuntimeError, TypeError, KeyError, ArithmeticError,
        sqlite3.DatabaseError, zipfile.BadZipFile, UnicodeDecodeError,
    ) as exc:
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--jobs-json", type=Path, required=True)
    parser.add_argument("--artifacts-json", type=Path, required=True)
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.source_run_id < 1 or args.source_attempt < 1:
        parser.error("source worker identity must be positive")
    try:
        receipt = audit_trend_handoff(
            run=_json_file(args.run_json),
            jobs=_json_file(args.jobs_json),
            artifacts=_json_file(args.artifacts_json),
            archive=args.artifact_zip,
            repository=args.repository,
            source_run_id=args.source_run_id,
            source_attempt=args.source_attempt,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        receipt = {
            "status": "unverified", "reasons": [
                f"{type(exc).__name__}: {exc}",
            ],
            "research_only": True, "paper_only": True,
            "promotion_authority": False, "execution_authority": False,
        }
    _write_json_atomic(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
