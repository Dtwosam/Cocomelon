from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore

ZERO: Final = Decimal("0")
MIN_ATTRIBUTED_TRADES_FOR_REVIEW: Final = 30
LATENCY_BANDS_MS: Final = (
    (0, 1_000, "<1s"),
    (1_000, 5_000, "1-<5s"),
    (5_000, 15_000, "5-<15s"),
    (15_000, 30_000, "15-<30s"),
    (30_000, 60_000, "30-<60s"),
    (60_000, None, "60s+"),
)


class EntryDecisionAgeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EntryDecisionAgeObservation:
    trade_id: str
    market: str
    direction: str
    lead_strategy: str
    decision_timestamp_ms: int
    opened_at_ms: int
    decision_age_ms: int
    net_pnl: Decimal
    net_r: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.market,
            self.direction,
            self.lead_strategy,
        ):
            if not value.strip():
                raise ValueError("entry-age identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.decision_timestamp_ms < 0 or self.opened_at_ms < 0:
            raise ValueError("entry-age timestamps must be non-negative")
        if self.opened_at_ms < self.decision_timestamp_ms:
            raise ValueError("entry fill must not precede decision")
        if self.decision_age_ms != (
            self.opened_at_ms - self.decision_timestamp_ms
        ):
            raise ValueError("entry decision age must reconcile")
        if not self.net_pnl.is_finite() or not self.net_r.is_finite():
            raise ValueError("entry-age economics must be finite")


def _fact_for_trade(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
) -> DecisionEvaluationFact | None:
    if trade.replay_run_id is None:
        return None
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        trade.replay_run_id,
    )
    if fact is None:
        return None
    if fact.market != trade.market:
        raise EntryDecisionAgeError(
            "entry-age decision market does not match trade"
        )
    if fact.direction is not trade.direction:
        raise EntryDecisionAgeError(
            "entry-age decision direction does not match trade"
        )
    if fact.feature_snapshot_id != trade.feature_snapshot_id:
        raise EntryDecisionAgeError(
            "entry-age feature lineage does not match trade"
        )
    return fact


def _band(age_ms: int) -> str:
    if age_ms < 0:
        raise ValueError("decision age must be non-negative")
    for lower, upper, label in LATENCY_BANDS_MS:
        if age_ms < lower:
            continue
        if upper is None or age_ms < upper:
            return label
    raise AssertionError("unreachable decision-age band")


def _nearest_rank(values: Sequence[int], fraction: Decimal) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = int(
        (
            Decimal(len(ordered) - 1) * fraction
        ).to_integral_value(rounding=ROUND_HALF_UP)
    )
    return ordered[rank]


def _summary(
    observations: Sequence[EntryDecisionAgeObservation],
) -> dict[str, object]:
    items = tuple(observations)
    count = len(items)
    if not items:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "net_pnl": "0",
            "mean_net_r": None,
            "mean_decision_age_ms": None,
            "median_decision_age_ms": None,
            "p90_decision_age_ms": None,
            "max_decision_age_ms": None,
        }
    ages = tuple(item.decision_age_ms for item in items)
    net_pnl = sum((item.net_pnl for item in items), ZERO)
    return {
        "trades": count,
        "wins": sum(1 for item in items if item.net_pnl > ZERO),
        "losses": sum(1 for item in items if item.net_pnl < ZERO),
        "breakeven": sum(1 for item in items if item.net_pnl == ZERO),
        "net_pnl": str(net_pnl),
        "mean_net_r": str(
            sum((item.net_r for item in items), ZERO)
            / Decimal(count)
        ),
        "mean_decision_age_ms": sum(ages) // count,
        "median_decision_age_ms": _nearest_rank(
            ages,
            Decimal("0.5"),
        ),
        "p90_decision_age_ms": _nearest_rank(
            ages,
            Decimal("0.9"),
        ),
        "max_decision_age_ms": max(ages),
    }


def _grouped(
    observations: Sequence[EntryDecisionAgeObservation],
    *,
    field: str,
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[EntryDecisionAgeObservation]] = {}
    for item in observations:
        value = getattr(item, field)
        if not isinstance(value, str):
            raise EntryDecisionAgeError(
                "entry-age grouping field must be string"
            )
        groups.setdefault(value, []).append(item)
    return {
        label: _summary(tuple(items))
        for label, items in sorted(groups.items())
    }


def entry_decision_age_summary(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    observations: list[EntryDecisionAgeObservation] = []
    attribution_misses = 0

    for trade in journal.iter_trades():
        fact = _fact_for_trade(trade, fact_store)
        if fact is None or fact.lead_strategy is None:
            attribution_misses += 1
            continue
        if trade.opened_at_ms < fact.timestamp_ms:
            raise EntryDecisionAgeError(
                "entry fill timestamp precedes strategy decision"
            )
        observations.append(
            EntryDecisionAgeObservation(
                trade_id=trade.trade_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                lead_strategy=fact.lead_strategy,
                decision_timestamp_ms=fact.timestamp_ms,
                opened_at_ms=trade.opened_at_ms,
                decision_age_ms=(
                    trade.opened_at_ms - fact.timestamp_ms
                ),
                net_pnl=trade.net_pnl,
                net_r=trade.net_r,
            )
        )

    resolved = tuple(observations)
    bands: dict[str, dict[str, object]] = {}
    for _lower, _upper, label in LATENCY_BANDS_MS:
        bands[label] = _summary(
            tuple(
                item
                for item in resolved
                if _band(item.decision_age_ms) == label
            )
        )

    overall = _summary(resolved)
    attributed = len(resolved)
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "strategy_decision_timestamp_to_first_opening_fill"
        ),
        "attributed_closed_trades": attributed,
        "attribution_misses": attribution_misses,
        "minimum_attributed_trades_for_review": (
            MIN_ATTRIBUTED_TRADES_FOR_REVIEW
        ),
        "ready_for_review": (
            attributed >= MIN_ATTRIBUTED_TRADES_FOR_REVIEW
            and attribution_misses == 0
        ),
        "still_needed_for_review": max(
            0,
            MIN_ATTRIBUTED_TRADES_FOR_REVIEW - attributed,
        ),
        "older_than_5s": sum(
            1 for item in resolved if item.decision_age_ms >= 5_000
        ),
        "older_than_15s": sum(
            1 for item in resolved if item.decision_age_ms >= 15_000
        ),
        "older_than_30s": sum(
            1 for item in resolved if item.decision_age_ms >= 30_000
        ),
        "older_than_60s": sum(
            1 for item in resolved if item.decision_age_ms >= 60_000
        ),
        "overall": overall,
        "by_age_band": bands,
        "by_side": _grouped(resolved, field="direction"),
        "by_lead_strategy": _grouped(
            resolved,
            field="lead_strategy",
        ),
    }
