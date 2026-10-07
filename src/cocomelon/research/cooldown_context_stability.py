from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import product
from typing import Final, cast

ZERO: Final = Decimal("0")
COOLDOWN_CONTEXT_STABILITY_SCHEMA_VERSION = 2
EXPECTED_COOLDOWN_CANDIDATE_ID: Final = (
    "prospective-consecutive-loss-cooldown-relaxation-v1"
)
ONE_HOUR_MS: Final = 60 * 60 * 1_000
DEFAULT_SPLIT_FRACTION = Decimal("0.60")
DEFAULT_MIN_DISCOVERY_ROWS = 8
DEFAULT_MIN_VALIDATION_ROWS = 6
DEFAULT_MIN_VALIDATION_MARKETS = 3
DEFAULT_MIN_DISCOVERY_POSITIVE_SHARE = Decimal("0.60")
DEFAULT_MIN_VALIDATION_POSITIVE_SHARE = Decimal("0.55")
DEFAULT_VALIDATION_BLOCK_COUNT = 2
DEFAULT_MIN_VALIDATION_BLOCK_ROWS = 2
DEFAULT_MIN_VALIDATION_BLOCK_POSITIVE_SHARE = Decimal("0.50")
CANDIDATE_DIMENSION_SETS: Final = (
    ("relaxation_window_ms", "lead_strategy"),
    ("relaxation_window_ms", "lead_strategy", "direction"),
    ("relaxation_window_ms", "lead_strategy", "elapsed_bucket"),
    ("relaxation_window_ms", "lead_strategy", "rank_band"),
    (
        "relaxation_window_ms",
        "lead_strategy",
        "direction",
        "elapsed_bucket",
    ),
)


class CooldownContextStabilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Outcome:
    timestamp_ms: int
    market: str
    relaxation_window_ms: str
    direction: str
    lead_strategy: str
    elapsed_bucket: str
    rank_band: str
    fee_adjusted_pnl_1h: Decimal
    directional_return_1h: Decimal

    def value(self, dimension: str) -> str:
        value = getattr(self, dimension)
        if not isinstance(value, str):
            raise CooldownContextStabilityError(
                f"unsupported context dimension: {dimension}"
            )
        return value


@dataclass(frozen=True, slots=True)
class CooldownContextCandidate:
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    discovery_rows: int
    discovery_markets: int
    discovery_positive_share: Decimal
    discovery_total_pnl: Decimal
    discovery_mean_return: Decimal
    validation_rows: int
    validation_markets: int
    validation_positive_share: Decimal | None
    validation_total_pnl: Decimal | None
    validation_mean_return: Decimal | None
    validation_leave_one_option_min_pnl: Decimal | None
    validation_leave_one_market_min_pnl: Decimal | None
    validation_block_rows: tuple[int, ...]
    validation_block_positive_shares: tuple[Decimal | None, ...]
    validation_block_pnl: tuple[Decimal, ...]
    validation_blocks_consistent: int
    stable_on_validation: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "dimensions": self.dimensions,
            "values": self.values,
            "discovery_rows": self.discovery_rows,
            "discovery_markets": self.discovery_markets,
            "discovery_positive_share": str(self.discovery_positive_share),
            "discovery_total_pnl": str(self.discovery_total_pnl),
            "discovery_mean_return": str(self.discovery_mean_return),
            "validation_rows": self.validation_rows,
            "validation_markets": self.validation_markets,
            "validation_positive_share": (
                None
                if self.validation_positive_share is None
                else str(self.validation_positive_share)
            ),
            "validation_total_pnl": (
                None
                if self.validation_total_pnl is None
                else str(self.validation_total_pnl)
            ),
            "validation_mean_return": (
                None
                if self.validation_mean_return is None
                else str(self.validation_mean_return)
            ),
            "validation_leave_one_option_min_pnl": (
                None
                if self.validation_leave_one_option_min_pnl is None
                else str(self.validation_leave_one_option_min_pnl)
            ),
            "validation_leave_one_market_min_pnl": (
                None
                if self.validation_leave_one_market_min_pnl is None
                else str(self.validation_leave_one_market_min_pnl)
            ),
            "validation_block_rows": self.validation_block_rows,
            "validation_block_positive_shares": tuple(
                None if value is None else str(value)
                for value in self.validation_block_positive_shares
            ),
            "validation_block_pnl": tuple(
                str(value) for value in self.validation_block_pnl
            ),
            "validation_blocks_consistent": (
                self.validation_blocks_consistent
            ),
            "stable_on_validation": self.stable_on_validation,
            "strategy_authority": False,
            "risk_authority": False,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class CooldownContextStabilityReport:
    source_option_count: int
    settled_1h_outcomes: int
    split_timestamp_ms: int | None
    discovery_rows: int
    validation_rows: int
    candidates: tuple[CooldownContextCandidate, ...]
    schema_version: int = COOLDOWN_CONTEXT_STABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "source_option_count": self.source_option_count,
            "settled_1h_outcomes": self.settled_1h_outcomes,
            "split_timestamp_ms": self.split_timestamp_ms,
            "discovery_rows": self.discovery_rows,
            "validation_rows": self.validation_rows,
            "candidate_count": len(self.candidates),
            "stable_candidate_count": sum(
                item.stable_on_validation for item in self.candidates
            ),
            "candidates": tuple(item.to_dict() for item in self.candidates),
            "candidate_dimension_sets": CANDIDATE_DIMENSION_SETS,
            "direction_only_candidates_allowed": False,
            "lead_strategy_context_required": True,
            "relaxation_window_context_required": True,
            "window_eligible_outcomes_only": True,
            "one_hour_fee_adjusted_execution_economics_required": True,
            "chronological_holdout_required": True,
            "leave_one_option_robustness_required": True,
            "leave_one_market_robustness_required": True,
            "validation_block_consistency_required": True,
            "research_only": True,
            "descriptive_only": True,
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
        raise CooldownContextStabilityError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CooldownContextStabilityError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CooldownContextStabilityError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise CooldownContextStabilityError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CooldownContextStabilityError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise CooldownContextStabilityError(f"{field} must be finite")
    return result


def _rank_band(value: int) -> str:
    if value <= 3:
        return "top3"
    if value <= 10:
        return "top10"
    return "outside10"


def _outcomes(summary: dict[str, object]) -> tuple[_Outcome, ...]:
    raw_options = summary.get("option_results")
    if not isinstance(raw_options, list):
        raise CooldownContextStabilityError(
            "cooldown option_results must be a list"
        )
    raw_windows = summary.get("relaxed_cooldown_windows_ms")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise CooldownContextStabilityError(
            "relaxed_cooldown_windows_ms must be a non-empty list"
        )
    configured_windows: set[int] = set()
    for raw_window in raw_windows:
        window_ms = _integer(raw_window, "relaxed_cooldown_window_ms")
        if window_ms <= 0:
            raise CooldownContextStabilityError(
                "relaxed cooldown windows must be positive"
            )
        if window_ms in configured_windows:
            raise CooldownContextStabilityError(
                "relaxed cooldown windows must be unique"
            )
        configured_windows.add(window_ms)

    outcomes: list[_Outcome] = []
    for raw_value in raw_options:
        raw = _mapping(raw_value, "cooldown option")
        markouts = _mapping(raw.get("markouts"), "markouts")
        markout = _mapping(markouts.get(str(ONE_HOUR_MS)), "1h markout")
        if markout.get("status") != "settled":
            continue
        raw_applicable = raw.get("applicable_relaxed_windows_ms")
        if not isinstance(raw_applicable, list):
            raise CooldownContextStabilityError(
                "applicable_relaxed_windows_ms must be a list"
            )
        applicable: list[int] = []
        for raw_window in raw_applicable:
            window_ms = _integer(
                raw_window,
                "applicable_relaxed_window_ms",
            )
            if window_ms not in configured_windows:
                raise CooldownContextStabilityError(
                    "applicable relaxation window is not configured"
                )
            if window_ms in applicable:
                raise CooldownContextStabilityError(
                    "applicable relaxation windows must be unique"
                )
            applicable.append(window_ms)
        if not applicable:
            continue

        pnl = _decimal(
            markout.get("entry_fee_adjusted_mark_to_market_pnl"),
            "entry_fee_adjusted_mark_to_market_pnl",
        )
        directional_return = _decimal(
            markout.get("directional_return_fraction"),
            "directional_return_fraction",
        )
        for window_ms in applicable:
            outcomes.append(
                _Outcome(
                    timestamp_ms=_integer(
                        raw.get("timestamp_ms"),
                        "timestamp_ms",
                    ),
                    market=_string(raw.get("market"), "market"),
                    relaxation_window_ms=str(window_ms),
                    direction=_string(raw.get("direction"), "direction"),
                    lead_strategy=_string(
                        raw.get("lead_strategy"),
                        "lead_strategy",
                    ),
                    elapsed_bucket=_string(
                        raw.get("elapsed_bucket"),
                        "elapsed_bucket",
                    ),
                    rank_band=_rank_band(
                        _integer(raw.get("rank_ordinal"), "rank_ordinal")
                    ),
                    fee_adjusted_pnl_1h=pnl,
                    directional_return_1h=directional_return,
                )
            )
    return tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.timestamp_ms,
                item.market,
                int(item.relaxation_window_ms),
                item.lead_strategy,
                item.direction,
            ),
        )
    )


def _validate_source(summary: dict[str, object]) -> None:
    if summary.get("candidate_id") != EXPECTED_COOLDOWN_CANDIDATE_ID:
        raise CooldownContextStabilityError(
            "cooldown candidate identity is unsupported"
        )
    if (
        summary.get("research_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("changes_risk_limits") is not False
        or summary.get("forward_markout_only") is not True
        or summary.get("realized_pnl_modeled") is not False
    ):
        raise CooldownContextStabilityError(
            "cooldown source authority or claim scope drift"
        )


def _split(
    rows: tuple[_Outcome, ...],
    *,
    split_fraction: Decimal,
) -> tuple[int | None, tuple[_Outcome, ...], tuple[_Outcome, ...]]:
    if not rows:
        return None, (), ()
    timestamps = tuple(sorted({item.timestamp_ms for item in rows}))
    if len(timestamps) < 2:
        return timestamps[0], rows, ()
    split_index = int(Decimal(len(timestamps)) * split_fraction)
    split_index = max(1, min(split_index, len(timestamps) - 1))
    split_timestamp_ms = timestamps[split_index]
    discovery = tuple(
        item for item in rows if item.timestamp_ms < split_timestamp_ms
    )
    validation = tuple(
        item for item in rows if item.timestamp_ms >= split_timestamp_ms
    )
    return split_timestamp_ms, discovery, validation


def _keys(
    item: _Outcome,
    dimensions: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(values)
        for values in product(
            *((item.value(dimension),) for dimension in dimensions)
        )
    )


def _positive_share(rows: tuple[_Outcome, ...]) -> Decimal | None:
    if not rows:
        return None
    return Decimal(
        sum(item.fee_adjusted_pnl_1h > ZERO for item in rows)
    ) / Decimal(len(rows))


def _total_pnl(rows: tuple[_Outcome, ...]) -> Decimal:
    return sum((item.fee_adjusted_pnl_1h for item in rows), ZERO)


def _mean_return(rows: tuple[_Outcome, ...]) -> Decimal | None:
    if not rows:
        return None
    return sum(
        (item.directional_return_1h for item in rows),
        ZERO,
    ) / Decimal(len(rows))


def _leave_one_option_min_pnl(
    rows: tuple[_Outcome, ...],
) -> Decimal | None:
    if len(rows) < 2:
        return None
    total = _total_pnl(rows)
    return min(total - item.fee_adjusted_pnl_1h for item in rows)


def _leave_one_market_min_pnl(
    rows: tuple[_Outcome, ...],
) -> Decimal | None:
    by_market: dict[str, Decimal] = {}
    for item in rows:
        by_market[item.market] = (
            by_market.get(item.market, ZERO)
            + item.fee_adjusted_pnl_1h
        )
    if len(by_market) < 2:
        return None
    total = _total_pnl(rows)
    return min(total - pnl for pnl in by_market.values())


def _chronological_blocks(
    rows: tuple[_Outcome, ...],
    *,
    block_count: int,
) -> tuple[tuple[_Outcome, ...], ...]:
    if not rows:
        return ()
    timestamps = tuple(sorted({item.timestamp_ms for item in rows}))
    resolved = min(block_count, len(timestamps))
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


def build_cooldown_context_stability_report(
    summary: dict[str, object],
    *,
    split_fraction: Decimal = DEFAULT_SPLIT_FRACTION,
    min_discovery_rows: int = DEFAULT_MIN_DISCOVERY_ROWS,
    min_validation_rows: int = DEFAULT_MIN_VALIDATION_ROWS,
    min_validation_markets: int = DEFAULT_MIN_VALIDATION_MARKETS,
    min_discovery_positive_share: Decimal = (
        DEFAULT_MIN_DISCOVERY_POSITIVE_SHARE
    ),
    min_validation_positive_share: Decimal = (
        DEFAULT_MIN_VALIDATION_POSITIVE_SHARE
    ),
    validation_block_count: int = DEFAULT_VALIDATION_BLOCK_COUNT,
    min_validation_block_rows: int = DEFAULT_MIN_VALIDATION_BLOCK_ROWS,
    min_validation_block_positive_share: Decimal = (
        DEFAULT_MIN_VALIDATION_BLOCK_POSITIVE_SHARE
    ),
) -> CooldownContextStabilityReport:
    _validate_source(summary)
    if not ZERO < split_fraction < Decimal("1"):
        raise ValueError("split_fraction must be in (0, 1)")
    if min_discovery_rows <= 0 or min_validation_rows <= 0:
        raise ValueError("minimum row counts must be positive")
    if min_validation_markets <= 0:
        raise ValueError("min_validation_markets must be positive")
    if validation_block_count <= 0 or min_validation_block_rows <= 0:
        raise ValueError("validation block parameters must be positive")
    for value, field in (
        (
            min_discovery_positive_share,
            "min_discovery_positive_share",
        ),
        (
            min_validation_positive_share,
            "min_validation_positive_share",
        ),
        (
            min_validation_block_positive_share,
            "min_validation_block_positive_share",
        ),
    ):
        if not ZERO <= value <= Decimal("1"):
            raise ValueError(f"{field} must be in [0, 1]")

    rows = _outcomes(summary)
    split_timestamp_ms, discovery, validation = _split(
        rows,
        split_fraction=split_fraction,
    )
    candidates: list[CooldownContextCandidate] = []

    for dimensions in CANDIDATE_DIMENSION_SETS:
        discovery_groups: dict[tuple[str, ...], list[_Outcome]] = {}
        validation_groups: dict[tuple[str, ...], list[_Outcome]] = {}
        for item in discovery:
            for key in _keys(item, dimensions):
                discovery_groups.setdefault(key, []).append(item)
        for item in validation:
            for key in _keys(item, dimensions):
                validation_groups.setdefault(key, []).append(item)

        for values in sorted(discovery_groups):
            discovery_group = tuple(discovery_groups[values])
            discovery_positive = _positive_share(discovery_group)
            discovery_return = _mean_return(discovery_group)
            discovery_pnl = _total_pnl(discovery_group)
            if (
                len(discovery_group) < min_discovery_rows
                or discovery_positive is None
                or discovery_positive < min_discovery_positive_share
                or discovery_pnl <= ZERO
                or discovery_return is None
                or discovery_return <= ZERO
            ):
                continue

            validation_group = tuple(
                validation_groups.get(values, ())
            )
            validation_positive = _positive_share(validation_group)
            validation_pnl = (
                None
                if not validation_group
                else _total_pnl(validation_group)
            )
            validation_return = _mean_return(validation_group)
            loo_option = _leave_one_option_min_pnl(validation_group)
            loo_market = _leave_one_market_min_pnl(validation_group)
            blocks = _chronological_blocks(
                validation_group,
                block_count=validation_block_count,
            )
            block_rows = tuple(len(block) for block in blocks)
            block_positive = tuple(
                _positive_share(block) for block in blocks
            )
            block_pnl = tuple(_total_pnl(block) for block in blocks)
            consistent_blocks = sum(
                len(block) >= min_validation_block_rows
                and positive is not None
                and positive >= min_validation_block_positive_share
                and pnl > ZERO
                for block, positive, pnl in zip(
                    blocks,
                    block_positive,
                    block_pnl,
                    strict=True,
                )
            )
            validation_markets = len(
                {item.market for item in validation_group}
            )
            stable = (
                len(validation_group) >= min_validation_rows
                and validation_markets >= min_validation_markets
                and validation_positive is not None
                and validation_positive >= min_validation_positive_share
                and validation_pnl is not None
                and validation_pnl > ZERO
                and validation_return is not None
                and validation_return > ZERO
                and loo_option is not None
                and loo_option > ZERO
                and loo_market is not None
                and loo_market > ZERO
                and len(blocks) == validation_block_count
                and consistent_blocks == validation_block_count
            )
            candidates.append(
                CooldownContextCandidate(
                    dimensions=dimensions,
                    values=values,
                    discovery_rows=len(discovery_group),
                    discovery_markets=len(
                        {item.market for item in discovery_group}
                    ),
                    discovery_positive_share=discovery_positive,
                    discovery_total_pnl=discovery_pnl,
                    discovery_mean_return=discovery_return,
                    validation_rows=len(validation_group),
                    validation_markets=validation_markets,
                    validation_positive_share=validation_positive,
                    validation_total_pnl=validation_pnl,
                    validation_mean_return=validation_return,
                    validation_leave_one_option_min_pnl=loo_option,
                    validation_leave_one_market_min_pnl=loo_market,
                    validation_block_rows=block_rows,
                    validation_block_positive_shares=block_positive,
                    validation_block_pnl=block_pnl,
                    validation_blocks_consistent=consistent_blocks,
                    stable_on_validation=stable,
                )
            )

    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                not item.stable_on_validation,
                -item.validation_rows,
                item.dimensions,
                item.values,
            ),
        )
    )
    return CooldownContextStabilityReport(
        source_option_count=len(
            cast(list[object], summary.get("option_results", []))
        ),
        settled_1h_outcomes=len(rows),
        split_timestamp_ms=split_timestamp_ms,
        discovery_rows=len(discovery),
        validation_rows=len(validation),
        candidates=ordered,
    )
