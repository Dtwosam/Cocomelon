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
MIN_CLOSED_TRADES_PER_LANE: Final = 30
REVIEW_BLOCK_COUNT: Final = 3
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
    return _integer(
        raw,
        "matching_context_blocked_unattributed",
    )


def _validate_row_authority(row: dict[str, object]) -> None:
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
) -> tuple[dict[str, object], ...]:
    if not rows:
        return ()
    blocks: list[dict[str, object]] = []
    prior: dict[str, object] | None = None
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
    latest = None if not eligible else eligible[-1]
    duration_ms = (
        0
        if latest is None
        else max(
            0,
            _integer(latest.get("end_ms"), "end_ms")
            - freeze.prospective_not_before_ms,
        )
    )
    blocks = _chronological_blocks(eligible)

    reasons: list[str] = []
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

    if latest is None:
        reasons.append("no_eligible_checkpoints")
    else:
        admission = _candidate_admission(latest)
        matching = _matching_block_count(latest)
        unattributed_matching = _unattributed_block_count(latest)
        blocked_markets = _blocked_by_market(admission)
        baseline_closed = _lane_closed_trades(latest, "baseline")
        candidate_closed = _lane_closed_trades(latest, "candidate")
        candidate_lane = _mapping(latest.get("candidate"), "candidate")
        candidate_total_pnl = _decimal(
            candidate_lane.get("total_account_pnl"),
            "candidate.total_account_pnl",
        )
        candidate_realized_net = _decimal(
            candidate_lane.get("realized_net_pnl"),
            "candidate.realized_net_pnl",
        )
        total_advantage = _metric(
            latest,
            "candidate_minus_baseline_total_account_pnl",
        )
        realized_advantage = _metric(
            latest,
            "candidate_minus_baseline_realized_net_pnl",
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
        "future_duration_ms": duration_ms,
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
        "readiness_failures": tuple(reasons),
        "ready_for_review": not reasons,
        "thresholds": {
            "min_future_duration_ms": MIN_REVIEW_DURATION_MS,
            "min_review_checkpoints": MIN_REVIEW_CHECKPOINTS,
            "min_matching_context_blocks": MIN_MATCHING_CONTEXT_BLOCKS,
            "min_blocked_markets": MIN_BLOCKED_MARKETS,
            "max_dominant_blocked_market_share": str(
                MAX_DOMINANT_BLOCKED_MARKET_SHARE
            ),
            "min_closed_trades_per_lane": MIN_CLOSED_TRADES_PER_LANE,
            "review_block_count": REVIEW_BLOCK_COUNT,
            "min_matches_per_block": MIN_MATCHES_PER_BLOCK,
            "min_markets_per_block": MIN_MARKETS_PER_BLOCK,
            "positive_candidate_absolute_pnl_required": True,
            "positive_candidate_advantage_required": True,
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
