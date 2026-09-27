from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
)

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")
ENTRY_MARKOUT_HORIZONS_MS: Final = (
    60_000,
    300_000,
    900_000,
)
MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS: Final = 60_000
MAX_ENTRY_MARKOUT_RANK_AGE_MS: Final = 300_000


class EntryMarkoutError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EntryMarkoutObservation:
    trade_id: str
    market: str
    direction: str
    lead_strategy: str
    scanner_rank_bucket: str
    horizon_ms: int
    target_timestamp_ms: int
    observed_timestamp_ms: int
    observation_lag_ms: int
    mark_px: Decimal
    signed_return_fraction: Decimal
    signed_return_bps: Decimal
    gross_r: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.market,
            self.direction,
            self.lead_strategy,
            self.scanner_rank_bucket,
        ):
            if not value.strip():
                raise ValueError("markout identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.target_timestamp_ms < 0:
            raise ValueError(
                "target_timestamp_ms must be non-negative"
            )
        if self.observed_timestamp_ms < self.target_timestamp_ms:
            raise ValueError(
                "observed mark must not precede markout target"
            )
        if (
            self.observation_lag_ms
            != self.observed_timestamp_ms
            - self.target_timestamp_ms
        ):
            raise ValueError("markout observation lag must reconcile")
        if not self.mark_px.is_finite() or self.mark_px <= ZERO:
            raise ValueError("mark_px must be positive and finite")
        for metric in (
            self.signed_return_fraction,
            self.signed_return_bps,
            self.gross_r,
        ):
            if not metric.is_finite():
                raise ValueError("markout economics must be finite")


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EntryMarkoutError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise EntryMarkoutError(f"{field} must be finite")
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntryMarkoutError(f"{field} must be an integer")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EntryMarkoutError(
            f"{field} must be a non-empty string"
        )
    return value


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise EntryMarkoutError("duplicate journal trade id")
    return by_id


def _lead_strategy(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
) -> str | None:
    if trade.replay_run_id is None:
        return None
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        trade.replay_run_id,
    )
    if fact is None:
        return None
    if (
        fact.market != trade.market
        or fact.direction is not trade.direction
        or fact.feature_snapshot_id != trade.feature_snapshot_id
    ):
        raise EntryMarkoutError(
            "entry markout decision lineage mismatch"
        )
    return fact.lead_strategy


def _scanner_rank_bucket(
    trade: TradeJournalEntry,
    rank_store: ContinuousPaperOpeningRankStore | None,
) -> tuple[str, str | None, int | None]:
    if rank_store is None:
        return "unknown", None, None
    evidence = rank_store.load(trade.opening_plan_id)
    if evidence is None:
        return "unknown", "missing", None
    if (
        evidence.market != trade.market.canonical
        or evidence.opened_at_ms != trade.opened_at_ms
    ):
        raise EntryMarkoutError(
            "entry markout opening-rank lineage mismatch"
        )
    if evidence.rank_age_ms > MAX_ENTRY_MARKOUT_RANK_AGE_MS:
        return "stale", "stale", evidence.rank_age_ms
    if evidence.ordinal <= 5:
        bucket = "1-5"
    elif evidence.ordinal <= 10:
        bucket = "6-10"
    elif evidence.ordinal <= 20:
        bucket = "11-20"
    else:
        bucket = "21+"
    return bucket, None, evidence.rank_age_ms


def _verify_path_identity(
    raw: Mapping[str, object],
    trade: TradeJournalEntry,
) -> None:
    expected = {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "entry_price": str(trade.entry_price),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "filled_quantity": str(trade.filled_quantity),
    }
    actual = {
        "trade_id": raw.get("trade_id"),
        "market": raw.get("market"),
        "direction": raw.get("direction"),
        "opened_at_ms": raw.get("opened_at_ms"),
        "closed_at_ms": raw.get("closed_at_ms"),
        "entry_price": raw.get("entry_price"),
        "initial_risk_amount": raw.get("initial_risk_amount"),
        "filled_quantity": raw.get("filled_quantity"),
    }
    if actual != expected:
        raise EntryMarkoutError(
            "entry markout trade-path identity mismatch"
        )


def _marks(
    raw: Mapping[str, object],
) -> tuple[tuple[int, Decimal], ...]:
    value = raw.get("marks")
    if not isinstance(value, list):
        raise EntryMarkoutError("trade path marks must be an array")
    output: list[tuple[int, Decimal]] = []
    previous: int | None = None
    for item in value:
        if not isinstance(item, dict):
            raise EntryMarkoutError(
                "trade path mark must be an object"
            )
        timestamp_ms = _integer(
            item.get("available_at_ms"),
            "available_at_ms",
        )
        mark_px = _decimal(item.get("mark_px"), "mark_px")
        if mark_px <= ZERO:
            raise EntryMarkoutError(
                "trade path mark_px must be positive"
            )
        if previous is not None and timestamp_ms < previous:
            raise EntryMarkoutError(
                "trade path marks must be ordered"
            )
        previous = timestamp_ms
        output.append((timestamp_ms, mark_px))
    return tuple(output)


def _observation(
    trade: TradeJournalEntry,
    *,
    lead_strategy: str,
    scanner_rank_bucket: str,
    horizon_ms: int,
    marks: tuple[tuple[int, Decimal], ...],
) -> EntryMarkoutObservation | None:
    target_ms = trade.opened_at_ms + horizon_ms
    if trade.closed_at_ms < target_ms:
        return None
    chosen: tuple[int, Decimal] | None = None
    for timestamp_ms, mark_px in marks:
        if timestamp_ms >= target_ms:
            chosen = (timestamp_ms, mark_px)
            break
    if chosen is None:
        return None
    timestamp_ms, mark_px = chosen
    if timestamp_ms > trade.closed_at_ms:
        return None

    signed_move = (
        mark_px - trade.entry_price
        if trade.direction.value == "long"
        else trade.entry_price - mark_px
    )
    signed_fraction = signed_move / trade.entry_price
    gross_currency = signed_move * trade.filled_quantity
    gross_r = gross_currency / trade.initial_risk_amount
    return EntryMarkoutObservation(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        lead_strategy=lead_strategy,
        scanner_rank_bucket=scanner_rank_bucket,
        horizon_ms=horizon_ms,
        target_timestamp_ms=target_ms,
        observed_timestamp_ms=timestamp_ms,
        observation_lag_ms=timestamp_ms - target_ms,
        mark_px=mark_px,
        signed_return_fraction=signed_fraction,
        signed_return_bps=signed_fraction * BPS,
        gross_r=gross_r,
    )


def _summary(
    observations: tuple[EntryMarkoutObservation, ...],
) -> dict[str, object]:
    count = len(observations)
    if count == 0:
        return {
            "observations": 0,
            "positive": 0,
            "negative": 0,
            "flat": 0,
            "mean_signed_return_bps": None,
            "mean_gross_r": None,
            "mean_observation_lag_ms": None,
            "max_observation_lag_ms": None,
        }
    return {
        "observations": count,
        "positive": sum(
            1 for item in observations if item.gross_r > ZERO
        ),
        "negative": sum(
            1 for item in observations if item.gross_r < ZERO
        ),
        "flat": sum(
            1 for item in observations if item.gross_r == ZERO
        ),
        "mean_signed_return_bps": str(
            sum(
                (
                    item.signed_return_bps
                    for item in observations
                ),
                ZERO,
            )
            / Decimal(count)
        ),
        "mean_gross_r": str(
            sum(
                (item.gross_r for item in observations),
                ZERO,
            )
            / Decimal(count)
        ),
        "mean_observation_lag_ms": (
            sum(
                item.observation_lag_ms
                for item in observations
            )
            // count
        ),
        "max_observation_lag_ms": max(
            item.observation_lag_ms
            for item in observations
        ),
    }


def _grouped(
    observations: tuple[EntryMarkoutObservation, ...],
    field: str,
) -> dict[str, dict[str, object]]:
    labels: dict[str, list[EntryMarkoutObservation]] = {}
    for item in observations:
        value = getattr(item, field)
        if not isinstance(value, str):
            raise EntryMarkoutError(
                "entry markout grouping field must be string"
            )
        labels.setdefault(value, []).append(item)
    return {
        label: _summary(tuple(items))
        for label, items in sorted(labels.items())
    }


def entry_markout_summary(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    path_store: ContinuousPaperTradePathStore,
    rank_store: ContinuousPaperOpeningRankStore | None = None,
) -> dict[str, object]:
    trades = _trade_map(journal)
    path_payloads = path_store.iter_payloads()
    observations: list[EntryMarkoutObservation] = []
    incomplete_paths = 0
    missing_journal_trade = 0
    missing_decision_attribution = 0
    missing_rank_attribution = 0
    stale_rank_attribution = 0
    rank_ages: list[int] = []
    censored_by_horizon = {
        str(horizon): 0
        for horizon in ENTRY_MARKOUT_HORIZONS_MS
    }
    missing_mark_by_horizon = {
        str(horizon): 0
        for horizon in ENTRY_MARKOUT_HORIZONS_MS
    }
    stale_mark_by_horizon = {
        str(horizon): 0
        for horizon in ENTRY_MARKOUT_HORIZONS_MS
    }

    for raw in path_payloads:
        trade_id = _string(raw.get("trade_id"), "trade_id")
        trade = trades.get(trade_id)
        if trade is None:
            missing_journal_trade += 1
            continue
        _verify_path_identity(raw, trade)
        if raw.get("path_complete") is not True:
            incomplete_paths += 1
            continue
        lead_strategy = _lead_strategy(trade, fact_store)
        if lead_strategy is None:
            missing_decision_attribution += 1
            lead_strategy = "unknown"
        (
            scanner_rank_bucket,
            rank_issue,
            rank_age_ms,
        ) = _scanner_rank_bucket(trade, rank_store)
        if rank_issue == "missing":
            missing_rank_attribution += 1
        elif rank_issue == "stale":
            stale_rank_attribution += 1
        if rank_age_ms is not None:
            rank_ages.append(rank_age_ms)
        marks = _marks(raw)

        for horizon_ms in ENTRY_MARKOUT_HORIZONS_MS:
            target_ms = trade.opened_at_ms + horizon_ms
            if trade.closed_at_ms < target_ms:
                censored_by_horizon[str(horizon_ms)] += 1
                continue
            item = _observation(
                trade,
                lead_strategy=lead_strategy,
                scanner_rank_bucket=scanner_rank_bucket,
                horizon_ms=horizon_ms,
                marks=marks,
            )
            if item is None:
                missing_mark_by_horizon[str(horizon_ms)] += 1
                continue
            if (
                item.observation_lag_ms
                > MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS
            ):
                stale_mark_by_horizon[str(horizon_ms)] += 1
                continue
            observations.append(item)

    by_horizon: dict[str, dict[str, object]] = {}
    for horizon_ms in ENTRY_MARKOUT_HORIZONS_MS:
        horizon_observations = tuple(
            item
            for item in observations
            if item.horizon_ms == horizon_ms
        )
        by_horizon[str(horizon_ms)] = {
            **_summary(horizon_observations),
            "censored_before_horizon": (
                censored_by_horizon[str(horizon_ms)]
            ),
            "missing_observed_mark": (
                missing_mark_by_horizon[str(horizon_ms)]
            ),
            "stale_observed_mark": (
                stale_mark_by_horizon[str(horizon_ms)]
            ),
            "by_side": _grouped(
                horizon_observations,
                "direction",
            ),
            "by_lead_strategy": _grouped(
                horizon_observations,
                "lead_strategy",
            ),
            "by_scanner_rank_bucket": _grouped(
                horizon_observations,
                "scanner_rank_bucket",
            ),
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "first_observed_mark_at_or_after_horizon_within_max_lag"
        ),
        "max_observation_lag_ms": (
            MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS
        ),
        "horizons_ms": list(ENTRY_MARKOUT_HORIZONS_MS),
        "complete_path_records": (
            len(path_payloads) - incomplete_paths
        ),
        "incomplete_paths_skipped": incomplete_paths,
        "missing_journal_trade": missing_journal_trade,
        "missing_decision_attribution": (
            missing_decision_attribution
        ),
        "missing_rank_attribution": missing_rank_attribution,
        "stale_rank_attribution": stale_rank_attribution,
        "max_accepted_rank_age_ms": MAX_ENTRY_MARKOUT_RANK_AGE_MS,
        "mean_rank_age_ms": (
            None
            if not rank_ages
            else sum(rank_ages) // len(rank_ages)
        ),
        "max_rank_age_ms": (
            None if not rank_ages else max(rank_ages)
        ),
        "by_horizon_ms": by_horizon,
    }
