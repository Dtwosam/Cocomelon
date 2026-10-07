from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.cooldown_context_candidate import (
    EXPECTED_COOLDOWN_CANDIDATE_ID,
    CooldownContextCandidateFreeze,
    verify_cooldown_context_candidate_freeze,
)

ZERO: Final = Decimal("0")
ONE_HOUR_MS: Final = 60 * 60 * 1_000
COOLDOWN_CONTEXT_PROSPECTIVE_SCHEMA_VERSION = 1
PROSPECTIVE_REVIEW_MIN_OUTCOMES = 30
PROSPECTIVE_REVIEW_MIN_MARKETS = 4
PROSPECTIVE_REVIEW_MIN_POSITIVE_SHARE = Decimal("0.60")
PROSPECTIVE_REVIEW_BLOCK_COUNT = 3
PROSPECTIVE_REVIEW_MIN_BLOCK_ROWS = 5
PROSPECTIVE_REVIEW_MIN_BLOCK_POSITIVE_SHARE = Decimal("0.55")


class CooldownContextProspectiveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Outcome:
    timestamp_ms: int
    market: str
    pnl: Decimal
    directional_return: Decimal


@dataclass(frozen=True, slots=True)
class CooldownContextProspectiveReport:
    candidate_id: str
    candidate_dimensions: tuple[str, ...]
    candidate_values: tuple[str, ...]
    relaxation_window_ms: int
    lead_strategy: str
    prospective_not_before_ms: int
    source_max_timestamp_ms: int
    matching_outcomes: int
    matching_markets: int
    profitable_outcomes: int
    losing_outcomes: int
    flat_outcomes: int
    positive_share: Decimal | None
    total_fee_adjusted_pnl: Decimal
    mean_fee_adjusted_pnl: Decimal | None
    mean_directional_return: Decimal | None
    leave_one_option_min_pnl: Decimal | None
    leave_one_market_min_pnl: Decimal | None
    first_matching_timestamp_ms: int | None
    last_matching_timestamp_ms: int | None
    observation_span_ms: int
    prospective_block_rows: tuple[int, ...]
    prospective_block_positive_shares: tuple[Decimal | None, ...]
    prospective_block_pnl: tuple[Decimal, ...]
    prospective_blocks_consistent: int
    ready_for_review: bool
    schema_version: int = COOLDOWN_CONTEXT_PROSPECTIVE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_dimensions": self.candidate_dimensions,
            "candidate_values": self.candidate_values,
            "relaxation_window_ms": self.relaxation_window_ms,
            "lead_strategy": self.lead_strategy,
            "prospective_not_before_ms": self.prospective_not_before_ms,
            "source_max_timestamp_ms": self.source_max_timestamp_ms,
            "matching_outcomes": self.matching_outcomes,
            "matching_markets": self.matching_markets,
            "profitable_outcomes": self.profitable_outcomes,
            "losing_outcomes": self.losing_outcomes,
            "flat_outcomes": self.flat_outcomes,
            "positive_share": (
                None if self.positive_share is None else str(self.positive_share)
            ),
            "total_fee_adjusted_pnl": str(self.total_fee_adjusted_pnl),
            "mean_fee_adjusted_pnl": (
                None
                if self.mean_fee_adjusted_pnl is None
                else str(self.mean_fee_adjusted_pnl)
            ),
            "mean_directional_return": (
                None
                if self.mean_directional_return is None
                else str(self.mean_directional_return)
            ),
            "leave_one_option_min_pnl": (
                None
                if self.leave_one_option_min_pnl is None
                else str(self.leave_one_option_min_pnl)
            ),
            "leave_one_market_min_pnl": (
                None
                if self.leave_one_market_min_pnl is None
                else str(self.leave_one_market_min_pnl)
            ),
            "first_matching_timestamp_ms": self.first_matching_timestamp_ms,
            "last_matching_timestamp_ms": self.last_matching_timestamp_ms,
            "observation_span_ms": self.observation_span_ms,
            "prospective_block_rows": self.prospective_block_rows,
            "prospective_block_positive_shares": tuple(
                None if value is None else str(value)
                for value in self.prospective_block_positive_shares
            ),
            "prospective_block_pnl": tuple(
                str(value) for value in self.prospective_block_pnl
            ),
            "prospective_blocks_consistent": self.prospective_blocks_consistent,
            "review_gate": {
                "min_outcomes": PROSPECTIVE_REVIEW_MIN_OUTCOMES,
                "min_markets": PROSPECTIVE_REVIEW_MIN_MARKETS,
                "min_positive_share": str(
                    PROSPECTIVE_REVIEW_MIN_POSITIVE_SHARE
                ),
                "block_count": PROSPECTIVE_REVIEW_BLOCK_COUNT,
                "min_block_rows": PROSPECTIVE_REVIEW_MIN_BLOCK_ROWS,
                "min_block_positive_share": str(
                    PROSPECTIVE_REVIEW_MIN_BLOCK_POSITIVE_SHARE
                ),
                "positive_total_pnl_required": True,
                "positive_mean_return_required": True,
                "positive_leave_one_option_pnl_required": True,
                "positive_leave_one_market_pnl_required": True,
                "positive_block_pnl_required": True,
            },
            "ready_for_review": self.ready_for_review,
            "prospective_only": True,
            "paper_only": True,
            "research_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise CooldownContextProspectiveError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise CooldownContextProspectiveError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CooldownContextProspectiveError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CooldownContextProspectiveError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise CooldownContextProspectiveError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CooldownContextProspectiveError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise CooldownContextProspectiveError(f"{field} must be finite")
    return result


def _rank_band(value: int) -> str:
    if value <= 3:
        return "top3"
    if value <= 10:
        return "top10"
    return "outside10"


def _validate_source(summary: dict[str, object]) -> None:
    if summary.get("candidate_id") != EXPECTED_COOLDOWN_CANDIDATE_ID:
        raise CooldownContextProspectiveError(
            "cooldown candidate identity is unsupported"
        )
    if (
        summary.get("research_only") is not True
        or summary.get("descriptive_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("changes_risk_limits") is not False
        or summary.get("forward_markout_only") is not True
        or summary.get("realized_pnl_modeled") is not False
    ):
        raise CooldownContextProspectiveError(
            "cooldown source authority or claim scope drift"
        )


def _matches(
    raw: dict[str, object],
    freeze: CooldownContextCandidateFreeze,
) -> bool:
    context = dict(zip(freeze.dimensions, freeze.values, strict=True))
    for dimension, expected in context.items():
        if dimension == "relaxation_window_ms":
            raw_windows = _sequence(
                raw.get("applicable_relaxed_windows_ms"),
                "applicable_relaxed_windows_ms",
            )
            windows = tuple(
                _integer(item, "applicable_relaxed_window_ms")
                for item in raw_windows
            )
            if int(expected) not in windows:
                return False
        elif dimension == "rank_band":
            if _rank_band(_integer(raw.get("rank_ordinal"), "rank_ordinal")) != expected:
                return False
        else:
            if _string(raw.get(dimension), dimension) != expected:
                return False
    return True


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _leave_one_option_min_pnl(rows: tuple[_Outcome, ...]) -> Decimal | None:
    if len(rows) < 2:
        return None
    total = sum((item.pnl for item in rows), ZERO)
    return min(total - item.pnl for item in rows)


def _leave_one_market_min_pnl(rows: tuple[_Outcome, ...]) -> Decimal | None:
    by_market: dict[str, Decimal] = {}
    for item in rows:
        by_market[item.market] = by_market.get(item.market, ZERO) + item.pnl
    if len(by_market) < 2:
        return None
    total = sum(by_market.values(), ZERO)
    return min(total - pnl for pnl in by_market.values())


def _chronological_blocks(
    rows: tuple[_Outcome, ...],
    *,
    count: int,
) -> tuple[tuple[_Outcome, ...], ...]:
    if not rows:
        return ()
    timestamps = tuple(sorted({item.timestamp_ms for item in rows}))
    resolved = min(count, len(timestamps))
    blocks: list[tuple[_Outcome, ...]] = []
    for index in range(resolved):
        start = (len(timestamps) * index) // resolved
        end = (len(timestamps) * (index + 1)) // resolved
        selected = set(timestamps[start:end])
        if selected:
            blocks.append(
                tuple(
                    item
                    for item in rows
                    if item.timestamp_ms in selected
                )
            )
    return tuple(blocks)


def build_cooldown_context_prospective_report(
    summary: dict[str, object],
    freeze: CooldownContextCandidateFreeze,
) -> CooldownContextProspectiveReport:
    _validate_source(summary)

    raw_windows = _sequence(
        summary.get("relaxed_cooldown_windows_ms"),
        "relaxed_cooldown_windows_ms",
    )
    configured_windows = {
        _integer(item, "relaxed_cooldown_window_ms")
        for item in raw_windows
    }
    if freeze.relaxation_window_ms not in configured_windows:
        raise CooldownContextProspectiveError(
            "frozen relaxation window is no longer configured"
        )

    raw_options = _sequence(summary.get("option_results"), "option_results")
    source_max_timestamp_ms = 0
    outcomes: list[_Outcome] = []
    for raw_value in raw_options:
        raw = _mapping(raw_value, "cooldown option")
        timestamp_ms = _integer(raw.get("timestamp_ms"), "timestamp_ms")
        source_max_timestamp_ms = max(source_max_timestamp_ms, timestamp_ms)
        if timestamp_ms < freeze.prospective_not_before_ms:
            continue
        if not _matches(raw, freeze):
            continue

        markouts = _mapping(raw.get("markouts"), "markouts")
        markout = _mapping(markouts.get(str(ONE_HOUR_MS)), "1h markout")
        if markout.get("status") != "settled":
            continue
        outcomes.append(
            _Outcome(
                timestamp_ms=timestamp_ms,
                market=_string(raw.get("market"), "market"),
                pnl=_decimal(
                    markout.get("entry_fee_adjusted_mark_to_market_pnl"),
                    "entry_fee_adjusted_mark_to_market_pnl",
                ),
                directional_return=_decimal(
                    markout.get("directional_return_fraction"),
                    "directional_return_fraction",
                ),
            )
        )

    ordered = tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.timestamp_ms,
                item.market,
                item.pnl,
            ),
        )
    )
    pnl_values = tuple(item.pnl for item in ordered)
    return_values = tuple(item.directional_return for item in ordered)
    positive = sum(item.pnl > ZERO for item in ordered)
    negative = sum(item.pnl < ZERO for item in ordered)
    flat = len(ordered) - positive - negative
    positive_share = (
        None
        if not ordered
        else Decimal(positive) / Decimal(len(ordered))
    )
    total_pnl = sum(pnl_values, ZERO)
    mean_pnl = _mean(pnl_values)
    mean_return = _mean(return_values)
    loo_option = _leave_one_option_min_pnl(ordered)
    loo_market = _leave_one_market_min_pnl(ordered)

    blocks = _chronological_blocks(
        ordered,
        count=PROSPECTIVE_REVIEW_BLOCK_COUNT,
    )
    block_rows = tuple(len(block) for block in blocks)
    block_shares = tuple(
        (
            Decimal(sum(item.pnl > ZERO for item in block))
            / Decimal(len(block))
            if block
            else None
        )
        for block in blocks
    )
    block_pnl = tuple(
        sum((item.pnl for item in block), ZERO)
        for block in blocks
    )
    blocks_consistent = sum(
        len(block) >= PROSPECTIVE_REVIEW_MIN_BLOCK_ROWS
        and share is not None
        and share >= PROSPECTIVE_REVIEW_MIN_BLOCK_POSITIVE_SHARE
        and pnl > ZERO
        for block, share, pnl in zip(
            blocks,
            block_shares,
            block_pnl,
            strict=True,
        )
    )

    first = ordered[0].timestamp_ms if ordered else None
    last = ordered[-1].timestamp_ms if ordered else None
    span = 0 if first is None or last is None else last - first
    markets = len({item.market for item in ordered})
    ready = (
        len(ordered) >= PROSPECTIVE_REVIEW_MIN_OUTCOMES
        and markets >= PROSPECTIVE_REVIEW_MIN_MARKETS
        and positive_share is not None
        and positive_share >= PROSPECTIVE_REVIEW_MIN_POSITIVE_SHARE
        and total_pnl > ZERO
        and mean_return is not None
        and mean_return > ZERO
        and loo_option is not None
        and loo_option > ZERO
        and loo_market is not None
        and loo_market > ZERO
        and len(blocks) == PROSPECTIVE_REVIEW_BLOCK_COUNT
        and blocks_consistent == PROSPECTIVE_REVIEW_BLOCK_COUNT
    )

    return CooldownContextProspectiveReport(
        candidate_id=freeze.candidate_id,
        candidate_dimensions=freeze.dimensions,
        candidate_values=freeze.values,
        relaxation_window_ms=freeze.relaxation_window_ms,
        lead_strategy=freeze.lead_strategy,
        prospective_not_before_ms=freeze.prospective_not_before_ms,
        source_max_timestamp_ms=source_max_timestamp_ms,
        matching_outcomes=len(ordered),
        matching_markets=markets,
        profitable_outcomes=positive,
        losing_outcomes=negative,
        flat_outcomes=flat,
        positive_share=positive_share,
        total_fee_adjusted_pnl=total_pnl,
        mean_fee_adjusted_pnl=mean_pnl,
        mean_directional_return=mean_return,
        leave_one_option_min_pnl=loo_option,
        leave_one_market_min_pnl=loo_market,
        first_matching_timestamp_ms=first,
        last_matching_timestamp_ms=last,
        observation_span_ms=span,
        prospective_block_rows=block_rows,
        prospective_block_positive_shares=block_shares,
        prospective_block_pnl=block_pnl,
        prospective_blocks_consistent=blocks_consistent,
        ready_for_review=ready,
    )


def load_and_score_cooldown_context_candidate(
    *,
    cooldown_summary_path: str | Path,
    freeze_path: str | Path,
) -> CooldownContextProspectiveReport:
    try:
        raw = json.loads(Path(cooldown_summary_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CooldownContextProspectiveError(
            "cooldown summary is invalid"
        ) from exc
    summary = _mapping(raw, "cooldown summary")
    freeze = verify_cooldown_context_candidate_freeze(freeze_path)
    return build_cooldown_context_prospective_report(summary, freeze)
