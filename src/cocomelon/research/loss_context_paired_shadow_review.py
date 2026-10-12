from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)

ZERO: Final = Decimal("0")
LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_LEDGER_SCHEMA_VERSION: Final = 1
LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_SCHEMA_VERSION: Final = 1
LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_LEDGER_FILENAME: Final = "review-ledger.jsonl"

MIN_REVIEW_DURATION_MS: Final = 72 * 60 * 60 * 1000
MIN_REVIEW_CHECKPOINTS: Final = 9
MIN_MATCHING_CONTEXT_BLOCKS: Final = 30
MIN_BLOCKED_MARKETS: Final = 4
MAX_DOMINANT_BLOCKED_MARKET_SHARE: Final = Decimal("0.50")
MAX_FORWARD_MARKET_DATA_GAP_FRACTION: Final = Decimal("0.01")
MIN_CLOSED_TRADES_PER_LANE: Final = 30
MIN_CLOSED_TRADES_PER_DIRECTION: Final = 8
REVIEW_BLOCK_COUNT: Final = 3
SIGNED_PAIRED_CALENDAR_DAY_MS: Final = 24 * 60 * 60 * 1000
SIGNED_PAIRED_METRIC_KEYS: Final = (
    "candidate_total_account_pnl",
    "candidate_realized_net_pnl",
    "candidate_minus_baseline_total_account_pnl",
    "candidate_minus_baseline_realized_net_pnl",
)
MIN_MATCHES_PER_BLOCK: Final = 5
MIN_MARKETS_PER_BLOCK: Final = 2


class LossContextPairedShadowReviewError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextPairedShadowReviewError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextPairedShadowReviewError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LossContextPairedShadowReviewError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise LossContextPairedShadowReviewError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise LossContextPairedShadowReviewError(
            f"{field} must be finite"
        )
    return result


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LossContextPairedShadowReviewError(
            f"{field} must be a non-empty string"
        )
    return value


def _blocked_by_market(
    admission: dict[str, object],
) -> dict[str, int]:
    raw = _mapping(
        admission.get("matching_context_blocked_by_market"),
        "matching_context_blocked_by_market",
    )
    result: dict[str, int] = {}
    for market, value in raw.items():
        if not market:
            raise LossContextPairedShadowReviewError(
                "blocked market must be non-empty"
            )
        result[market] = _integer(
            value,
            f"matching_context_blocked_by_market[{market}]",
        )
    return dict(sorted(result.items()))


def _lane_closed_trades(row: dict[str, object], lane: str) -> int:
    payload = _mapping(row.get(lane), lane)
    return _integer(
        payload.get("closed_trade_count"),
        f"{lane}.closed_trade_count",
    )


def _side_counters(
    row: dict[str, object],
    lane: str,
) -> tuple[int, int, Decimal, Decimal] | None:
    """Only independently journaled closed after-cost trades count by side."""
    account = _mapping(row.get(lane), lane)
    fields = (
        "long_closed_trade_count", "short_closed_trade_count",
        "long_closed_net_pnl", "short_closed_net_pnl",
    )
    present = tuple(field in account for field in fields)
    if not any(present):
        return None
    if not all(present):
        raise LossContextPairedShadowReviewError(
            f"{lane} partial direction economics evidence"
        )
    longs = _integer(account[fields[0]], f"{lane}.{fields[0]}")
    shorts = _integer(account[fields[1]], f"{lane}.{fields[1]}")
    if longs + shorts > _lane_closed_trades(row, lane):
        raise LossContextPairedShadowReviewError(
            f"{lane} side counts exceed closed trades"
        )
    return (
        longs, shorts,
        _decimal(account[fields[2]], f"{lane}.{fields[2]}"),
        _decimal(account[fields[3]], f"{lane}.{fields[3]}"),
    )


def _validate_row_account_parity(row: dict[str, object]) -> None:
    """A reported A/B advantage must equal the two independent account snapshots."""
    baseline = _mapping(row.get("baseline"), "baseline")
    candidate = _mapping(row.get("candidate"), "candidate")
    for delta_field, account_field in (
        ("candidate_minus_baseline_equity", "equity"),
        ("candidate_minus_baseline_total_account_pnl", "total_account_pnl"),
        ("candidate_minus_baseline_realized_net_pnl", "realized_net_pnl"),
        ("candidate_minus_baseline_max_drawdown_fraction", "max_drawdown_fraction"),
    ):
        expected = (
            _decimal(candidate.get(account_field), f"candidate.{account_field}")
            - _decimal(baseline.get(account_field), f"baseline.{account_field}")
        )
        observed = _decimal(row.get(delta_field), delta_field)
        if observed != expected:
            raise LossContextPairedShadowReviewError(
                f"review ledger account delta mismatch: {delta_field}"
            )


def _gap_counters(
    row: dict[str, object],
) -> tuple[int, int, int] | None:
    """Legacy rows are readable, but lack data-coverage review credit."""
    fields = (
        "data_gap_closed_count",
        "data_gap_closed_duration_ms",
        "data_gap_open_count",
    )
    present = tuple(field in row for field in fields)
    if not any(present):
        return None
    if not all(present):
        raise LossContextPairedShadowReviewError(
            "partial market-data gap evidence"
        )
    return (
        _integer(row[fields[0]], fields[0]),
        _integer(row[fields[1]], fields[1]),
        _integer(row[fields[2]], fields[2]),
    )


def _candidate_admission(row: dict[str, object]) -> dict[str, object]:
    return _mapping(row.get("candidate_admission"), "candidate_admission")


def _matching_block_count(row: dict[str, object]) -> int:
    return sum(
        _blocked_by_market(_candidate_admission(row)).values()
    )


def _unattributed_block_count(row: dict[str, object]) -> int:
    admission = _candidate_admission(row)
    raw = admission.get("matching_context_blocked_unattributed")
    if raw is None:
        total = _integer(
            admission.get("matching_context_blocked"),
            "matching_context_blocked",
        )
        attributed = _matching_block_count(row)
        if attributed > total:
            raise LossContextPairedShadowReviewError(
                "attributed matching-context count exceeds total"
            )
        return total - attributed
    unattributed = _integer(
        raw,
        "matching_context_blocked_unattributed",
    )
    total = _integer(
        admission.get("matching_context_blocked"),
        "matching_context_blocked",
    )
    if _matching_block_count(row) + unattributed != total:
        raise LossContextPairedShadowReviewError(
            "matching-context block totals do not reconcile"
        )
    return unattributed


def _validate_row_authority(row: dict[str, object]) -> None:
    scope_lineage_clean = row.get("gap_scope_lineage_clean")
    if scope_lineage_clean is not None and type(scope_lineage_clean) is not bool:
        raise LossContextPairedShadowReviewError(
            "paired review gap scope lineage witness invalid"
        )
    for field in ("research_only", "shadow_only"):
        if row.get(field) is not True:
            raise LossContextPairedShadowReviewError(
                "review ledger authority mismatch"
            )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "changes_positions",
        "promotion_authority",
        "execution_authority",
    ):
        if row.get(field) is not False:
            raise LossContextPairedShadowReviewError(
                "review ledger authority mismatch"
            )


def verify_review_ledger(
    path: str | Path,
    *,
    candidate_id: str | None = None,
) -> tuple[dict[str, object], ...]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return ()

    rows: list[dict[str, object]] = []
    previous_digest: str | None = None
    previous_end_ms: int | None = None
    previous_matching = 0
    previous_unattributed = 0
    previous_markets: dict[str, int] = {}
    previous_baseline_closed = 0
    previous_candidate_closed = 0
    previous_candidate_id: str | None = None
    previous_loss_context_id: str | None = None
    previous_prospective_start: int | None = None
    previous_record_count = 0
    previous_gap_counters: tuple[int, int, int] | None = None
    previous_side_counters: dict[
        str, tuple[int, int, Decimal, Decimal] | None
    ] = {"baseline": None, "candidate": None}

    for line_number, line in enumerate(
        ledger_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LossContextPairedShadowReviewError(
                f"review ledger line {line_number} is invalid JSON"
            ) from exc
        row = _mapping(raw, f"review ledger line {line_number}")
        recorded_digest = _string(
            row.get("row_digest"),
            "row_digest",
        )
        unsigned = dict(row)
        unsigned.pop("row_digest", None)
        if _digest(unsigned) != recorded_digest:
            raise LossContextPairedShadowReviewError(
                "review ledger row digest mismatch"
            )
        if unsigned.get("previous_row_digest") != previous_digest:
            raise LossContextPairedShadowReviewError(
                "review ledger chain mismatch"
            )
        if (
            _integer(
                unsigned.get("schema_version"),
                "schema_version",
            )
            != LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_LEDGER_SCHEMA_VERSION
        ):
            raise LossContextPairedShadowReviewError(
                "review ledger schema mismatch"
            )
        row_candidate = _string(
            unsigned.get("portfolio_shadow_candidate_id"),
            "portfolio_shadow_candidate_id",
        )
        if candidate_id is not None and row_candidate != candidate_id:
            raise LossContextPairedShadowReviewError(
                "review ledger candidate mismatch"
            )
        _validate_row_authority(unsigned)
        _validate_row_account_parity(unsigned)
        gaps = _gap_counters(unsigned)
        sides = {lane: _side_counters(unsigned, lane) for lane in ("baseline", "candidate")}
        for lane, previous_side in previous_side_counters.items():
            current_side = sides[lane]
            if previous_side is not None and (
                current_side is None
                or current_side[0] < previous_side[0]
                or current_side[1] < previous_side[1]
            ):
                raise LossContextPairedShadowReviewError(
                    f"{lane} directional evidence disappeared or count regressed"
                )
        if previous_gap_counters is not None:
            if gaps is None:
                raise LossContextPairedShadowReviewError(
                    "market-data gap evidence disappeared"
                )
            if gaps[1] < previous_gap_counters[1]:
                raise LossContextPairedShadowReviewError(
                    "market-data closed gap duration moved backward"
                )
        loss_context_id = _string(
            unsigned.get("loss_context_candidate_id"),
            "loss_context_candidate_id",
        )
        prospective_start = _integer(
            unsigned.get("prospective_not_before_ms"),
            "prospective_not_before_ms",
        )
        record_count = _integer(unsigned.get("record_count"), "record_count")
        if (
            previous_candidate_id is not None
            and (
                row_candidate != previous_candidate_id
                or loss_context_id != previous_loss_context_id
                or prospective_start != previous_prospective_start
            )
        ):
            raise LossContextPairedShadowReviewError(
                "review ledger frozen candidate lineage changed"
            )
        if record_count < previous_record_count:
            raise LossContextPairedShadowReviewError(
                "review ledger record count moved backward"
            )

        end_ms = _integer(unsigned.get("end_ms"), "end_ms")
        if previous_end_ms is not None and end_ms <= previous_end_ms:
            raise LossContextPairedShadowReviewError(
                "review ledger chronology is not strictly increasing"
            )

        matching = _matching_block_count(unsigned)
        unattributed = _unattributed_block_count(unsigned)
        markets = _blocked_by_market(_candidate_admission(unsigned))
        baseline_closed = _lane_closed_trades(unsigned, "baseline")
        candidate_closed = _lane_closed_trades(unsigned, "candidate")
        if matching < previous_matching:
            raise LossContextPairedShadowReviewError(
                "matching-context attributed count moved backward"
            )
        if unattributed < previous_unattributed:
            raise LossContextPairedShadowReviewError(
                "matching-context unattributed count moved backward"
            )
        if baseline_closed < previous_baseline_closed:
            raise LossContextPairedShadowReviewError(
                "baseline closed-trade count moved backward"
            )
        if candidate_closed < previous_candidate_closed:
            raise LossContextPairedShadowReviewError(
                "candidate closed-trade count moved backward"
            )
        for market, value in previous_markets.items():
            if markets.get(market, 0) < value:
                raise LossContextPairedShadowReviewError(
                    "blocked-market count moved backward"
                )

        rows.append({**unsigned, "row_digest": recorded_digest})
        previous_digest = recorded_digest
        previous_end_ms = end_ms
        previous_matching = matching
        previous_unattributed = unattributed
        previous_markets = markets
        previous_baseline_closed = baseline_closed
        previous_candidate_closed = candidate_closed
        previous_candidate_id = row_candidate
        previous_loss_context_id = loss_context_id
        previous_prospective_start = prospective_start
        previous_record_count = record_count
        previous_gap_counters = gaps
        previous_side_counters = sides

    return tuple(rows)


def review_ledger_receipt(
    path: str | Path,
    *,
    candidate_id: str,
) -> dict[str, object]:
    rows = verify_review_ledger(path, candidate_id=candidate_id)
    return {
        "row_count": len(rows),
        "latest_row_digest": (
            None if not rows else rows[-1]["row_digest"]
        ),
    }


def append_review_checkpoint(
    path: str | Path,
    payload: dict[str, object],
) -> dict[str, object]:
    candidate_id = _string(
        payload.get("portfolio_shadow_candidate_id"),
        "portfolio_shadow_candidate_id",
    )
    rows = verify_review_ledger(path, candidate_id=candidate_id)
    previous_digest = (
        None if not rows else _string(rows[-1]["row_digest"], "row_digest")
    )
    if rows:
        previous_end_ms = _integer(rows[-1].get("end_ms"), "end_ms")
        end_ms = _integer(payload.get("end_ms"), "end_ms")
        if end_ms <= previous_end_ms:
            raise LossContextPairedShadowReviewError(
                "review checkpoint must advance chronology"
            )

    unsigned = {
        **payload,
        "previous_row_digest": previous_digest,
        "schema_version": (
            LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_LEDGER_SCHEMA_VERSION
        ),
    }
    _validate_row_authority(unsigned)
    _validate_row_account_parity(unsigned)
    current_gaps = _gap_counters(unsigned)
    current_sides = {
        lane: _side_counters(unsigned, lane)
        for lane in ("baseline", "candidate")
    }
    _unattributed_block_count(unsigned)
    if rows:
        previous = rows[-1]
        for lane in ("baseline", "candidate"):
            old_side = _side_counters(previous, lane)
            new_side = current_sides[lane]
            if old_side is not None and (
                new_side is None
                or new_side[0] < old_side[0]
                or new_side[1] < old_side[1]
            ):
                raise LossContextPairedShadowReviewError(
                    f"{lane} direction evidence regressed or disappeared"
                )
        prior_gaps = _gap_counters(previous)
        if prior_gaps is not None and (
            current_gaps is None
            or current_gaps[1] < prior_gaps[1]
        ):
            raise LossContextPairedShadowReviewError(
                "market-data closed gap duration regressed or disappeared"
            )
        if (
            unsigned.get("loss_context_candidate_id")
            != previous.get("loss_context_candidate_id")
            or unsigned.get("prospective_not_before_ms")
            != previous.get("prospective_not_before_ms")
        ):
            raise LossContextPairedShadowReviewError(
                "review ledger frozen candidate lineage changed"
            )
        if _integer(unsigned.get("record_count"), "record_count") < _integer(
            previous.get("record_count"), "record_count"
        ):
            raise LossContextPairedShadowReviewError(
                "review ledger record count moved backward"
            )
        if _matching_block_count(unsigned) < _matching_block_count(previous):
            raise LossContextPairedShadowReviewError(
                "matching-context attributed count moved backward"
            )
        if _unattributed_block_count(unsigned) < _unattributed_block_count(previous):
            raise LossContextPairedShadowReviewError(
                "matching-context unattributed count moved backward"
            )
        for market, count in _blocked_by_market(_candidate_admission(previous)).items():
            if _blocked_by_market(_candidate_admission(unsigned)).get(market, 0) < count:
                raise LossContextPairedShadowReviewError(
                    "blocked-market count moved backward"
                )
        for lane in ("baseline", "candidate"):
            if _lane_closed_trades(unsigned, lane) < _lane_closed_trades(previous, lane):
                raise LossContextPairedShadowReviewError(
                    f"{lane} closed-trade count moved backward"
                )
    row = {**unsigned, "row_digest": _digest(unsigned)}
    encoded = (_canonical_json(row) + "\n").encode("utf-8")
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return review_ledger_receipt(
        ledger_path,
        candidate_id=candidate_id,
    )


def _subtract_market_counts(
    end: dict[str, int],
    start: dict[str, int],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for market in sorted(set(end) | set(start)):
        value = end.get(market, 0) - start.get(market, 0)
        if value < 0:
            raise LossContextPairedShadowReviewError(
                "blocked-market count moved backward"
            )
        if value:
            result[market] = value
    return result


def _metric(row: dict[str, object], field: str) -> Decimal:
    return _decimal(row.get(field), field)


def _block_payload(
    rows: tuple[dict[str, object], ...],
    *,
    start_row: dict[str, object] | None,
) -> dict[str, object]:
    if not rows:
        raise LossContextPairedShadowReviewError(
            "review block must not be empty"
        )
    end = rows[-1]
    start_matching = (
        0 if start_row is None else _matching_block_count(start_row)
    )
    end_matching = _matching_block_count(end)
    matching = end_matching - start_matching
    if matching < 0:
        raise LossContextPairedShadowReviewError(
            "matching-context count moved backward"
        )
    start_markets = (
        {}
        if start_row is None
        else _blocked_by_market(_candidate_admission(start_row))
    )
    end_markets = _blocked_by_market(_candidate_admission(end))
    market_counts = _subtract_market_counts(end_markets, start_markets)
    total_advantage = _metric(
        end,
        "candidate_minus_baseline_total_account_pnl",
    ) - (
        ZERO
        if start_row is None
        else _metric(
            start_row,
            "candidate_minus_baseline_total_account_pnl",
        )
    )
    realized_advantage = _metric(
        end,
        "candidate_minus_baseline_realized_net_pnl",
    ) - (
        ZERO
        if start_row is None
        else _metric(
            start_row,
            "candidate_minus_baseline_realized_net_pnl",
        )
    )
    return {
        "start_ms": _integer(rows[0].get("end_ms"), "end_ms"),
        "end_ms": _integer(end.get("end_ms"), "end_ms"),
        "checkpoint_count": len(rows),
        "matching_context_blocks": matching,
        "blocked_markets": len(market_counts),
        "blocked_by_market": market_counts,
        "candidate_minus_baseline_total_account_pnl_delta": str(
            total_advantage
        ),
        "candidate_minus_baseline_realized_net_pnl_delta": str(
            realized_advantage
        ),
        "passes": (
            matching >= MIN_MATCHES_PER_BLOCK
            and len(market_counts) >= MIN_MARKETS_PER_BLOCK
            and total_advantage > ZERO
            and realized_advantage > ZERO
        ),
    }


def _chronological_blocks(
    rows: tuple[dict[str, object], ...],
    *,
    anchor: dict[str, object],
) -> tuple[dict[str, object], ...]:
    if not rows:
        return ()
    blocks: list[dict[str, object]] = []
    prior: dict[str, object] = anchor
    for index in range(REVIEW_BLOCK_COUNT):
        start = (len(rows) * index) // REVIEW_BLOCK_COUNT
        end = (len(rows) * (index + 1)) // REVIEW_BLOCK_COUNT
        selected = rows[start:end]
        if not selected:
            return ()
        blocks.append(
            _block_payload(
                selected,
                start_row=prior,
            )
        )
        prior = selected[-1]
    return tuple(blocks)



def _signed_account_metric(
    row: dict[str, object],
    key: str,
) -> Decimal:
    if key in (
        "candidate_minus_baseline_total_account_pnl",
        "candidate_minus_baseline_realized_net_pnl",
    ):
        return _metric(row, key)
    if not key.startswith("candidate_"):
        raise LossContextPairedShadowReviewError(
            "unsupported signed paired account metric " + key
        )
    account_field = key.removeprefix("candidate_")
    candidate = _mapping(row.get("candidate"), "candidate")
    return _decimal(
        candidate.get(account_field),
        "candidate." + account_field,
    )


def _fixed_signed_checkpoint_calendar_blocks(
    eligible: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """Attribute exact paired ACCOUNT snapshot deltas; never interpolate.

    A checkpoint-to-checkpoint transition crossing a calendar boundary has
    unknowable within-day PnL without finer signed samples. Put it in an
    explicit non-attributed bucket, not the most profitable adjacent day.
    """
    anchor = eligible[0] if eligible else None
    first_ms = (
        None if anchor is None
        else _integer(anchor.get("end_ms"), "end_ms")
    )
    buckets: dict[int, dict[str, object]] = {}
    crossing = {key: ZERO for key in SIGNED_PAIRED_METRIC_KEYS}
    crossing_intervals = 0
    for start, end in zip(eligible, eligible[1:], strict=False):
        if first_ms is None:
            raise LossContextPairedShadowReviewError(
                "paired calendar anchor cannot be missing"
            )
        previous_ms = _integer(start.get("end_ms"), "end_ms")
        current_ms = _integer(end.get("end_ms"), "end_ms")
        if previous_ms < first_ms or current_ms <= previous_ms:
            raise LossContextPairedShadowReviewError(
                "signed calendar checkpoints are not strictly ordered"
            )
        start_index = (
            previous_ms - first_ms
        ) // SIGNED_PAIRED_CALENDAR_DAY_MS
        end_index = (
            current_ms - first_ms
        ) // SIGNED_PAIRED_CALENDAR_DAY_MS
        delta = {
            key: (
                _signed_account_metric(end, key)
                - _signed_account_metric(start, key)
            )
            for key in SIGNED_PAIRED_METRIC_KEYS
        }
        if start_index != end_index:
            crossing_intervals += 1
            for key, value in delta.items():
                crossing[key] += value
            continue
        bucket = buckets.setdefault(end_index, {
            "transitions": 0,
            "values": {key: ZERO for key in SIGNED_PAIRED_METRIC_KEYS},
        })
        bucket["transitions"] = cast(int, bucket["transitions"]) + 1
        values = cast(dict[str, Decimal], bucket["values"])
        for key, value in delta.items():
            values[key] += value

    days: list[dict[str, object]] = []
    for index in sorted(set(buckets).union({0, 1})):
        data = buckets.get(index)
        values = (
            {key: ZERO for key in SIGNED_PAIRED_METRIC_KEYS}
            if data is None
            else cast(dict[str, Decimal], data["values"])
        )
        calendar_start_ms = (
            None if first_ms is None
            else first_ms + index * SIGNED_PAIRED_CALENDAR_DAY_MS
        )
        days.append({
            "calendar_day_index": index,
            "checkpoint_end_ms_ge": calendar_start_ms,
            "checkpoint_end_ms_lt": (
                None if calendar_start_ms is None
                else calendar_start_ms + SIGNED_PAIRED_CALENDAR_DAY_MS
            ),
            "fully_within_day_signed_checkpoint_transitions": (
                0 if data is None else data["transitions"]
            ),
            "signed_candidate_total_account_pnl_delta": str(
                values["candidate_total_account_pnl"]
            ),
            "signed_candidate_realized_net_pnl_delta": str(
                values["candidate_realized_net_pnl"]
            ),
            "signed_candidate_minus_baseline_total_account_pnl_delta": str(
                values["candidate_minus_baseline_total_account_pnl"]
            ),
            "signed_candidate_minus_baseline_realized_net_pnl_delta": str(
                values["candidate_minus_baseline_realized_net_pnl"]
            ),
            "all_boundary_transitions_assigned_to_day": False,
            "source_market_data_gap_free_for_day_certified": False,
            "complete_day_signed_economics_certified": False,
            "promotion_authority": False,
        })

    if anchor is not None:
        latest = eligible[-1]
        for key in SIGNED_PAIRED_METRIC_KEYS:
            original = (
                _signed_account_metric(latest, key)
                - _signed_account_metric(anchor, key)
            )
            attributed = sum((
                cast(dict[str, Decimal], b["values"])[key]
                for b in buckets.values()
            ), ZERO)
            if original != attributed + crossing[key]:
                raise LossContextPairedShadowReviewError(
                    "signed fixed-calendar account economics do not reconcile "
                    + key
                )
    if sum(
        cast(int, b["transitions"]) for b in buckets.values()
    ) + crossing_intervals != max(0, len(eligible) - 1):
        raise LossContextPairedShadowReviewError(
            "signed fixed-calendar checkpoint interval count mismatch"
        )
    return {
        "calendar_anchor_first_eligible_checkpoint_end_ms": first_ms,
        "fixed_calendar_day_ms": SIGNED_PAIRED_CALENDAR_DAY_MS,
        "signed_account_snapshot_based": bool(eligible),
        "signed_full_forward_account_pnl_partition_reconciles": bool(eligible),
        "within_day_signed_checkpoint_transitions": sum(
            cast(int, b["transitions"]) for b in buckets.values()
        ),
        "cross_boundary_unattributed_checkpoint_transitions": (
            crossing_intervals
        ),
        "cross_boundary_unattributed_account_delta": {
            key: str(value) for key, value in crossing.items()
        },
        "fixed_calendar_checkpoint_day_blocks": tuple(days),
        "count_partition_blocks_move_on_append": True,
        "calendar_boundaries_prevent_pnl_cherry_pick": True,
        "no_interpolation_or_cross_boundary_assignment": True,
        "mature_complete_calendar_day_certified": False,
        "source_gap_free_interval_certified": False,
        "positive_full_account_paired_edge_certified": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def build_paired_shadow_review(
    freeze: LossContextPortfolioShadowFreeze,
    ledger_path: str | Path,
) -> dict[str, object]:
    rows = verify_review_ledger(
        ledger_path,
        candidate_id=freeze.candidate_id,
    )
    eligible = tuple(
        row
        for row in rows
        if _integer(row.get("end_ms"), "end_ms")
        >= freeze.prospective_not_before_ms
    )
    anchor = None if not eligible else eligible[0]
    latest = None if not eligible else eligible[-1]
    evidence_rows = () if len(eligible) < 2 else eligible[1:]
    duration_ms = (
        0
        if anchor is None or latest is None
        else max(
            0,
            _integer(latest.get("end_ms"), "end_ms")
            - _integer(anchor.get("end_ms"), "end_ms"),
        )
    )
    fixed_calendar = _fixed_signed_checkpoint_calendar_blocks(eligible)
    blocks = (
        ()
        if anchor is None
        else _chronological_blocks(
            evidence_rows,
            anchor=anchor,
        )
    )

    reasons: list[str] = []
    # A pre-v2 shadow flattened every source-scoped gap into anonymous
    # global debt on resume. Its historical A/B and coverage evidence
    # cannot certify any future strategy, even when newer rows are clean.
    gap_scope_lineage_clean = bool(eligible) and all(
        row.get("gap_scope_lineage_clean") is True for row in eligible
    )
    # The first archived trend checkpoint may be pre-embargo. In that
    # case there are *no* eligible forward rows, which is missing evidence,
    # not proof the live actor restored a legacy flattened-gap account.
    # Keep the review closed; distinguish the two failure diagnoses.
    if eligible and not gap_scope_lineage_clean:
        reasons.append("unverifiable_legacy_gap_scope_lineage")
    if duration_ms < MIN_REVIEW_DURATION_MS:
        reasons.append("insufficient_future_duration")
    if len(eligible) < MIN_REVIEW_CHECKPOINTS:
        reasons.append("insufficient_checkpoints")

    matching = 0
    unattributed_matching = 0
    blocked_markets: dict[str, int] = {}
    baseline_closed = 0
    candidate_closed = 0
    candidate_total_pnl = ZERO
    candidate_realized_net = ZERO
    total_advantage = ZERO
    realized_advantage = ZERO
    drawdown_delta = ZERO
    dominant_market_share: Decimal | None = None
    forward_gap_duration_ms: int | None = None
    forward_gap_fraction: Decimal | None = None
    latest_open_gaps: int | None = None
    side_performance: dict[str, object] = {}
    realized_cashflow_decomposition: dict[str, object] = {
        "signed_forward_interval_certified": False,
        "reason": "missing_complete_forward_side_attribution",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    if eligible and any(
        _side_counters(row, lane) is None
        for row in eligible
        for lane in ("baseline", "candidate")
    ):
        reasons.append("missing_forward_direction_economics")
    elif anchor is not None and latest is not None:
        for lane in ("baseline", "candidate"):
            start = _side_counters(anchor, lane)
            end = _side_counters(latest, lane)
            assert start is not None and end is not None
            long_count = end[0] - start[0]
            short_count = end[1] - start[1]
            long_net = end[2] - start[2]
            short_net = end[3] - start[3]
            # Older checkpoint offsets can contain legitimately unclassified
            # pre-upgrade trades. Only new trades after the same frozen
            # evidence anchor may earn directional promotion credit.
            forward_closed = (
                _lane_closed_trades(latest, lane)
                - _lane_closed_trades(anchor, lane)
            )
            attributed_closed = long_count + short_count
            lane_start = _mapping(anchor.get(lane), "anchor." + lane)
            lane_end = _mapping(latest.get(lane), "latest." + lane)
            signed_realized = (
                _decimal(
                    lane_end.get("realized_net_pnl"),
                    "latest." + lane + ".realized_net_pnl",
                )
                - _decimal(
                    lane_start.get("realized_net_pnl"),
                    "anchor." + lane + ".realized_net_pnl",
                )
            )
            closed_side_cash = long_net + short_net
            side_residual = signed_realized - closed_side_cash
            side_performance[lane] = {
                "long_closed_trades": long_count,
                "short_closed_trades": short_count,
                "attributed_forward_closed_trades": attributed_closed,
                "total_forward_closed_trades": forward_closed,
                "long_realized_net_pnl": str(long_net),
                "short_realized_net_pnl": str(short_net),
                "closed_trade_side_net_cash_sum": str(closed_side_cash),
                "signed_account_realized_net_pnl_forward": str(
                    signed_realized
                ),
                "side_unattributed_realized_cashflow_residual": str(
                    side_residual
                ),
                "side_residual_cause_proven": False,
                "unattributed_open_fee_funding_timing_possible_not_proven": True,
            }
            if attributed_closed != forward_closed:
                reasons.append(f"{lane}_incomplete_forward_direction_attribution")
            if long_count < MIN_CLOSED_TRADES_PER_DIRECTION:
                reasons.append(f"{lane}_insufficient_long_closed_trades")
            if short_count < MIN_CLOSED_TRADES_PER_DIRECTION:
                reasons.append(f"{lane}_insufficient_short_closed_trades")
            if lane == "candidate":
                if long_net <= ZERO:
                    reasons.append("candidate_long_realized_net_pnl_not_positive")
                if short_net <= ZERO:
                    reasons.append("candidate_short_realized_net_pnl_not_positive")


    if (
        "baseline" in side_performance
        and "candidate" in side_performance
    ):
        baseline_side = _mapping(
            side_performance["baseline"], "baseline side economics",
        )
        candidate_side = _mapping(
            side_performance["candidate"], "candidate side economics",
        )
        candidate_signed = _decimal(
            candidate_side["signed_account_realized_net_pnl_forward"],
            "candidate signed forward realized net",
        )
        baseline_signed = _decimal(
            baseline_side["signed_account_realized_net_pnl_forward"],
            "baseline signed forward realized net",
        )
        signed_advantage = candidate_signed - baseline_signed
        side_advantage = (
            _decimal(
                candidate_side["closed_trade_side_net_cash_sum"],
                "candidate closed-side net",
            )
            - _decimal(
                baseline_side["closed_trade_side_net_cash_sum"],
                "baseline closed-side net",
            )
        )
        residual_advantage = (
            _decimal(
                candidate_side["side_unattributed_realized_cashflow_residual"],
                "candidate residual",
            )
            - _decimal(
                baseline_side["side_unattributed_realized_cashflow_residual"],
                "baseline residual",
            )
        )
        if signed_advantage != side_advantage + residual_advantage:
            raise LossContextPairedShadowReviewError(
                "paired closed-side net and residual cash do not reconcile"
            )
        realized_cashflow_decomposition = {
            "signed_forward_interval_certified": True,
            "forward_signed_baseline_realized_net_cash": str(
                baseline_signed
            ),
            "forward_signed_candidate_realized_net_cash": str(
                candidate_signed
            ),
            "forward_signed_candidate_minus_baseline_cash": str(
                signed_advantage
            ),
            "closed_side_candidate_minus_baseline_net_cash": str(
                side_advantage
            ),
            "unattributed_candidate_minus_baseline_cash_residual": str(
                residual_advantage
            ),
            "sum_closed_side_plus_residual_equals_signed_account": True,
            "residual_is_not_attributed_to_market_or_side": True,
            "residual_may_include_open_entry_fees_funding_or_timing": True,
            "source_of_residual_independently_proven": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    if eligible and not all(_gap_counters(row) is not None for row in eligible):
        reasons.append("missing_forward_market_data_gap_evidence")
    elif anchor is not None and latest is not None:
        start_gaps = _gap_counters(anchor)
        end_gaps = _gap_counters(latest)
        assert start_gaps is not None and end_gaps is not None
        forward_gap_duration_ms = end_gaps[1] - start_gaps[1]
        if forward_gap_duration_ms < 0:
            raise LossContextPairedShadowReviewError(
                "forward market-data gap duration moved backward"
            )
        latest_open_gaps = end_gaps[2]
        if latest_open_gaps:
            reasons.append("market_data_gap_still_open")
        if duration_ms > 0:
            forward_gap_fraction = (
                Decimal(forward_gap_duration_ms) / Decimal(duration_ms)
            )
            if forward_gap_fraction > MAX_FORWARD_MARKET_DATA_GAP_FRACTION:
                reasons.append("excessive_forward_market_data_gaps")

    if latest is None or anchor is None:
        reasons.append("no_eligible_checkpoints")
    else:
        latest_admission = _candidate_admission(latest)
        anchor_admission = _candidate_admission(anchor)
        matching = (
            _matching_block_count(latest)
            - _matching_block_count(anchor)
        )
        unattributed_matching = (
            _unattributed_block_count(latest)
            - _unattributed_block_count(anchor)
        )
        blocked_markets = _subtract_market_counts(
            _blocked_by_market(latest_admission),
            _blocked_by_market(anchor_admission),
        )
        baseline_closed = (
            _lane_closed_trades(latest, "baseline")
            - _lane_closed_trades(anchor, "baseline")
        )
        candidate_closed = (
            _lane_closed_trades(latest, "candidate")
            - _lane_closed_trades(anchor, "candidate")
        )
        candidate_lane = _mapping(latest.get("candidate"), "candidate")
        anchor_candidate_lane = _mapping(
            anchor.get("candidate"), "anchor.candidate"
        )
        # All denominators exclude the first eligible checkpoint. Test
        # absolute after-cost account edge and A/B advantage on precisely
        # that same forward interval, not cumulative pre-anchor gains.
        candidate_total_pnl = (
            _decimal(candidate_lane.get("total_account_pnl"),
                     "candidate.total_account_pnl")
            - _decimal(anchor_candidate_lane.get("total_account_pnl"),
                       "anchor.candidate.total_account_pnl")
        )
        candidate_realized_net = (
            _decimal(candidate_lane.get("realized_net_pnl"),
                     "candidate.realized_net_pnl")
            - _decimal(anchor_candidate_lane.get("realized_net_pnl"),
                       "anchor.candidate.realized_net_pnl")
        )
        total_advantage = (
            _metric(latest, "candidate_minus_baseline_total_account_pnl")
            - _metric(anchor, "candidate_minus_baseline_total_account_pnl")
        )
        realized_advantage = (
            _metric(latest, "candidate_minus_baseline_realized_net_pnl")
            - _metric(anchor, "candidate_minus_baseline_realized_net_pnl")
        )
        drawdown_delta = _metric(
            latest,
            "candidate_minus_baseline_max_drawdown_fraction",
        )
        if matching > 0 and blocked_markets:
            dominant_market_share = (
                Decimal(max(blocked_markets.values()))
                / Decimal(matching)
            )

    if matching < MIN_MATCHING_CONTEXT_BLOCKS:
        reasons.append("insufficient_matching_context_blocks")
    if len(blocked_markets) < MIN_BLOCKED_MARKETS:
        reasons.append("insufficient_blocked_market_diversity")
    if (
        dominant_market_share is not None
        and dominant_market_share > MAX_DOMINANT_BLOCKED_MARKET_SHARE
    ):
        reasons.append("blocked_context_market_concentration_too_high")
    if baseline_closed < MIN_CLOSED_TRADES_PER_LANE:
        reasons.append("insufficient_baseline_closed_trades")
    if candidate_closed < MIN_CLOSED_TRADES_PER_LANE:
        reasons.append("insufficient_candidate_closed_trades")
    if candidate_total_pnl <= ZERO:
        reasons.append("candidate_total_account_pnl_not_positive")
    if candidate_realized_net <= ZERO:
        reasons.append("candidate_realized_net_pnl_not_positive")
    if total_advantage <= ZERO:
        reasons.append("candidate_not_ahead_on_total_account_pnl")
    if realized_advantage <= ZERO:
        reasons.append("candidate_not_ahead_on_realized_net_pnl")
    if drawdown_delta > ZERO:
        reasons.append("candidate_max_drawdown_worse_than_baseline")
    if len(blocks) != REVIEW_BLOCK_COUNT:
        reasons.append("insufficient_chronological_blocks")
    elif any(block.get("passes") is not True for block in blocks):
        reasons.append("chronological_block_consistency_failed")

    return {
        "portfolio_shadow_candidate_id": freeze.candidate_id,
        "loss_context_candidate_id": freeze.loss_context_candidate_id,
        "dimensions": freeze.dimensions,
        "values": freeze.values,
        "prospective_not_before_ms": freeze.prospective_not_before_ms,
        "eligible_checkpoint_count": len(eligible),
        "evidence_checkpoint_count": len(evidence_rows),
        "review_anchor_end_ms": (
            None
            if anchor is None
            else _integer(anchor.get("end_ms"), "end_ms")
        ),
        "future_duration_ms": duration_ms,
        "forward_market_data_gap_duration_ms": forward_gap_duration_ms,
        "forward_market_data_gap_fraction": (
            None if forward_gap_fraction is None else str(forward_gap_fraction)
        ),
        "latest_open_market_data_gaps": latest_open_gaps,
        "gap_scope_lineage_clean": gap_scope_lineage_clean,
        "gap_scope_lineage_evidence_status": (
            "no_forward_checkpoint"
            if not eligible
            else (
                "unverifiable_legacy_or_missing_scope"
                if not gap_scope_lineage_clean else "forward_scope_clean"
            )
        ),
        "forward_closed_trade_economics_by_direction": side_performance,
        "forward_signed_account_realized_cashflow_decomposition": (
            realized_cashflow_decomposition
        ),
        "realized_cashflow_decomposition_does_not_change_readiness": True,
        "matching_context_blocks": matching,
        "unattributed_legacy_matching_context_blocks": (
            unattributed_matching
        ),
        "blocked_market_count": len(blocked_markets),
        "blocked_by_market": blocked_markets,
        "dominant_blocked_market_share": (
            None
            if dominant_market_share is None
            else str(dominant_market_share)
        ),
        "baseline_closed_trade_count": baseline_closed,
        "candidate_closed_trade_count": candidate_closed,
        "candidate_total_account_pnl": str(candidate_total_pnl),
        "candidate_realized_net_pnl": str(candidate_realized_net),
        "candidate_account_economics_window": "after_first_eligible_checkpoint",
        "candidate_cumulative_total_account_pnl": (
            None if latest is None else str(
                _decimal(
                    _mapping(latest.get("candidate"), "candidate").get(
                        "total_account_pnl"
                    ),
                    "candidate.total_account_pnl",
                )
            )
        ),
        "candidate_cumulative_realized_net_pnl": (
            None if latest is None else str(
                _decimal(
                    _mapping(latest.get("candidate"), "candidate").get(
                        "realized_net_pnl"
                    ),
                    "candidate.realized_net_pnl",
                )
            )
        ),
        "candidate_minus_baseline_total_account_pnl": str(
            total_advantage
        ),
        "candidate_minus_baseline_realized_net_pnl": str(
            realized_advantage
        ),
        "candidate_minus_baseline_max_drawdown_fraction": str(
            drawdown_delta
        ),
        "chronological_blocks": blocks,
        "fixed_calendar_signed_account_diagnostics": fixed_calendar,
        "chronological_blocks_move_with_checkpoint_count": True,
        "fixed_calendar_account_diagnostics_do_not_change_review_gate": True,
        "readiness_failures": tuple(reasons),
        "ready_for_review": not reasons,
        "thresholds": {
            "min_future_duration_ms": MIN_REVIEW_DURATION_MS,
            "max_forward_market_data_gap_fraction": str(
                MAX_FORWARD_MARKET_DATA_GAP_FRACTION
            ),
            "complete_prospective_data_gap_evidence_required": True,
            "no_open_gap_at_final_checkpoint_required": True,
            "min_review_checkpoints": MIN_REVIEW_CHECKPOINTS,
            "min_matching_context_blocks": MIN_MATCHING_CONTEXT_BLOCKS,
            "min_blocked_markets": MIN_BLOCKED_MARKETS,
            "max_dominant_blocked_market_share": str(
                MAX_DOMINANT_BLOCKED_MARKET_SHARE
            ),
            "min_closed_trades_per_lane": MIN_CLOSED_TRADES_PER_LANE,
            "min_closed_trades_per_direction": MIN_CLOSED_TRADES_PER_DIRECTION,
            "positive_candidate_realized_net_pnl_each_direction_required": True,
            "complete_future_direction_economics_required": True,
            "review_block_count": REVIEW_BLOCK_COUNT,
            "min_matches_per_block": MIN_MATCHES_PER_BLOCK,
            "min_markets_per_block": MIN_MARKETS_PER_BLOCK,
            "positive_candidate_absolute_pnl_required": True,
            "positive_candidate_advantage_required": True,
            "complete_attribution_for_forward_closed_trades_required": True,
            "account_profit_and_advantage_measured_after_anchor": True,
            "candidate_drawdown_not_worse_required": True,
            "positive_advantage_in_every_block_required": True,
        },
        "direction_only_filter_allowed": False,
        "candidate_difference_is_opening_admission_only": True,
        "research_only": True,
        "shadow_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "schema_version": LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_SCHEMA_VERSION,
    }
