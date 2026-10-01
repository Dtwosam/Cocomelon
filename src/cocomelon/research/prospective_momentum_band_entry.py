from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)

STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-zero-strike-momentum-band-v1"
STOP_EXIT_REASON: Final = "MARK_STOP_TRIGGERED"
MIN_SIGNED_RETURN_1H: Final = Decimal("0.015")
MAX_SIGNED_DAY_RETURN: Final = Decimal("0.10")
EMBARGO_MS: Final = 6 * 60 * 60 * 1_000
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_BLOCKED_TRADES: Final = 5
MIN_ADMITTED_TRADES: Final = 10
MIN_DIRECTION_CLOSED_TRADES: Final = 5
ZERO: Final = Decimal("0")


class ProspectiveMomentumBandEntryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveMomentumBandEntryState:
    frozen_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported momentum-band state schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported momentum-band candidate")

    @property
    def started_at_ms(self) -> int:
        return self.frozen_at_ms + EMBARGO_MS

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "frozen_at_ms": self.frozen_at_ms,
            "started_at_ms": self.started_at_ms,
            "embargo_ms": EMBARGO_MS,
            "rule": {
                "scope": "candidate_zero_strike_only",
                "market_direction_keyed": True,
                "min_signed_return_1h": str(MIN_SIGNED_RETURN_1H),
                "max_signed_day_return": str(MAX_SIGNED_DAY_RETURN),
                "block_if": (
                    "signed_return_1h_below_min_or_"
                    "signed_day_return_above_max"
                ),
                "missing_feature_action": "admit_fail_open",
                "losing_stop_action": "increment_candidate_strikes",
                "non_losing_stop_action": "reset_candidate_strikes",
                "blocked_actual_outcome_updates_state": False,
                "direction_specific": False,
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveMomentumBandEntryState:
        if not isinstance(raw, dict):
            raise ProspectiveMomentumBandEntryError(
                "momentum-band state must be an object"
            )
        expected = cls(frozen_at_ms=0).payload()["rule"]
        if raw.get("rule") != expected:
            raise ProspectiveMomentumBandEntryError(
                "momentum-band rule does not match frozen candidate"
            )
        if raw.get("embargo_ms") != EMBARGO_MS:
            raise ProspectiveMomentumBandEntryError(
                "momentum-band embargo does not match frozen candidate"
            )
        schema_version = raw.get("schema_version")
        frozen_at_ms = raw.get("frozen_at_ms")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectiveMomentumBandEntryError(
                "schema_version must be an integer"
            )
        if isinstance(frozen_at_ms, bool) or not isinstance(
            frozen_at_ms,
            int,
        ):
            raise ProspectiveMomentumBandEntryError(
                "frozen_at_ms must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectiveMomentumBandEntryError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise ProspectiveMomentumBandEntryError(
                "candidate_id must be a string"
            )
        try:
            state = cls(
                frozen_at_ms=frozen_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise ProspectiveMomentumBandEntryError(
                str(exc)
            ) from exc
        if started_at_ms != state.started_at_ms:
            raise ProspectiveMomentumBandEntryError(
                "started_at_ms does not match frozen embargo"
            )
        return state


def _qualifying_loss(trade: TradeJournalEntry) -> bool:
    return (
        trade.exit_reason == STOP_EXIT_REASON
        and trade.net_pnl < ZERO
    )


def _signed(value: Decimal, direction: Direction) -> Decimal:
    return value if direction is Direction.LONG else -value


def _direction_summary(
    trades: tuple[TradeJournalEntry, ...],
    blocked_ids: set[str],
    direction: Direction,
) -> dict[str, object]:
    values = tuple(
        trade for trade in trades if trade.direction is direction
    )
    blocked = tuple(
        trade for trade in values if trade.trade_id in blocked_ids
    )
    admitted = tuple(
        trade for trade in values if trade.trade_id not in blocked_ids
    )
    actual_pnl = sum((trade.net_pnl for trade in values), ZERO)
    candidate_pnl = sum(
        (trade.net_pnl for trade in admitted),
        ZERO,
    )
    actual_r = sum((trade.net_r for trade in values), ZERO)
    candidate_r = sum(
        (trade.net_r for trade in admitted),
        ZERO,
    )
    return {
        "closed_trades": len(values),
        "admitted_trades": len(admitted),
        "blocked_trades": len(blocked),
        "blocked_winners": sum(
            1 for trade in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade in blocked if trade.net_pnl < ZERO
        ),
        "blocked_net_pnl": str(
            sum((trade.net_pnl for trade in blocked), ZERO)
        ),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl": str(candidate_pnl),
        "delta_net_pnl": str(candidate_pnl - actual_pnl),
        "actual_net_r": str(actual_r),
        "candidate_net_r": str(candidate_r),
        "delta_net_r": str(candidate_r - actual_r),
    }


def prospective_momentum_band_entry_summary(
    trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveMomentumBandEntryState,
) -> dict[str, object]:
    prospective = tuple(
        sorted(
            (
                trade
                for trade in trades
                if trade.opened_at_ms >= state.started_at_ms
            ),
            key=lambda trade: (
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    trade_ids = tuple(trade.trade_id for trade in prospective)
    if len(set(trade_ids)) != len(trade_ids):
        raise ProspectiveMomentumBandEntryError(
            "prospective trades contain duplicate trade ids"
        )

    strikes: dict[tuple[str, Direction], int] = {}
    admitted_ids: set[str] = set()
    blocked_ids: set[str] = set()
    prior_strikes_by_trade: dict[str, int] = {}
    decision_details: dict[str, dict[str, object]] = {}
    missing_feature_ids: set[str] = set()
    zero_strike_feature_evaluated = 0
    nonzero_strike_bypass = 0
    events: list[tuple[int, int, TradeJournalEntry]] = []
    for trade in prospective:
        events.append((trade.closed_at_ms, 0, trade))
        events.append((trade.opened_at_ms, 1, trade))
    events.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2].opened_at_ms,
            item[2].trade_id,
        )
    )

    for _timestamp_ms, event_kind, trade in events:
        key = (trade.market.canonical, trade.direction)
        if event_kind == 1:
            prior_strikes = strikes.get(key, 0)
            prior_strikes_by_trade[trade.trade_id] = prior_strikes
            detail: dict[str, object] = {
                "prior_strikes": prior_strikes,
                "feature_snapshot_id": trade.feature_snapshot_id,
                "decision": "ADMIT",
                "reason": "nonzero_strike_bypass",
            }
            if prior_strikes > 0:
                nonzero_strike_bypass += 1
                admitted_ids.add(trade.trade_id)
                decision_details[trade.trade_id] = detail
                continue

            try:
                verified = feature_store.load(
                    trade.feature_snapshot_id
                )
            except Exception as exc:
                raise ProspectiveMomentumBandEntryError(
                    "opening feature snapshot could not be verified"
                ) from exc
            if verified is None:
                missing_feature_ids.add(trade.trade_id)
                detail["reason"] = "missing_feature_fail_open"
                admitted_ids.add(trade.trade_id)
                decision_details[trade.trade_id] = detail
                continue

            snapshot = verified.snapshot
            if snapshot.market != trade.market:
                raise ProspectiveMomentumBandEntryError(
                    "opening feature market does not match trade"
                )
            if snapshot.as_of_ms > trade.opened_at_ms:
                raise ProspectiveMomentumBandEntryError(
                    "opening feature snapshot is from the future"
                )
            if (
                snapshot.return_1h is None
                or snapshot.day_return is None
            ):
                missing_feature_ids.add(trade.trade_id)
                detail["reason"] = "incomplete_feature_fail_open"
                admitted_ids.add(trade.trade_id)
                decision_details[trade.trade_id] = detail
                continue

            zero_strike_feature_evaluated += 1
            signed_return_1h = _signed(
                snapshot.return_1h,
                trade.direction,
            )
            signed_day_return = _signed(
                snapshot.day_return,
                trade.direction,
            )
            should_block = (
                signed_return_1h < MIN_SIGNED_RETURN_1H
                or signed_day_return > MAX_SIGNED_DAY_RETURN
            )
            detail.update(
                {
                    "signed_return_1h": str(signed_return_1h),
                    "signed_day_return": str(signed_day_return),
                    "decision": "BLOCK" if should_block else "ADMIT",
                    "reason": (
                        "momentum_band"
                        if should_block
                        else "momentum_band_pass"
                    ),
                }
            )
            if should_block:
                blocked_ids.add(trade.trade_id)
            else:
                admitted_ids.add(trade.trade_id)
            decision_details[trade.trade_id] = detail
            continue

        if trade.trade_id not in admitted_ids:
            continue
        if _qualifying_loss(trade):
            strikes[key] = strikes.get(key, 0) + 1
        else:
            strikes[key] = 0

    if admitted_ids & blocked_ids:
        raise ProspectiveMomentumBandEntryError(
            "trade cannot be both admitted and blocked"
        )
    if len(admitted_ids | blocked_ids) != len(prospective):
        raise ProspectiveMomentumBandEntryError(
            "candidate decisions do not cover prospective trades"
        )

    blocked = tuple(
        trade for trade in prospective if trade.trade_id in blocked_ids
    )
    admitted = tuple(
        trade for trade in prospective if trade.trade_id in admitted_ids
    )
    actual_pnl = sum(
        (trade.net_pnl for trade in prospective),
        ZERO,
    )
    candidate_pnl = sum(
        (trade.net_pnl for trade in admitted),
        ZERO,
    )
    actual_r = sum(
        (trade.net_r for trade in prospective),
        ZERO,
    )
    candidate_r = sum(
        (trade.net_r for trade in admitted),
        ZERO,
    )
    delta_pnl = candidate_pnl - actual_pnl
    delta_r = candidate_r - actual_r
    robustness = prospective_filter_robustness(
        tuple(
            (
                trade,
                trade.trade_id in blocked_ids,
            )
            for trade in prospective
        )
    )

    by_direction = {
        direction.value: _direction_summary(
            prospective,
            blocked_ids,
            direction,
        )
        for direction in (Direction.LONG, Direction.SHORT)
    }
    blocked_by_market: dict[str, dict[str, object]] = {}
    for market in sorted(
        {trade.market.canonical for trade in blocked}
    ):
        cohort = tuple(
            trade
            for trade in blocked
            if trade.market.canonical == market
        )
        blocked_by_market[market] = {
            "trades": len(cohort),
            "wins": sum(
                1 for trade in cohort if trade.net_pnl > ZERO
            ),
            "losses": sum(
                1 for trade in cohort if trade.net_pnl < ZERO
            ),
            "net_pnl": str(
                sum((trade.net_pnl for trade in cohort), ZERO)
            ),
            "net_r": str(
                sum((trade.net_r for trade in cohort), ZERO)
            ),
        }

    long_closed = by_direction[Direction.LONG.value]["closed_trades"]
    short_closed = by_direction[Direction.SHORT.value]["closed_trades"]
    if (
        isinstance(long_closed, bool)
        or not isinstance(long_closed, int)
        or isinstance(short_closed, bool)
        or not isinstance(short_closed, int)
    ):
        raise ProspectiveMomentumBandEntryError(
            "direction counts must be integers"
        )

    missing_total = max(
        0,
        MIN_PROSPECTIVE_CLOSED_TRADES - len(prospective),
    )
    missing_blocked = max(
        0,
        MIN_BLOCKED_TRADES - len(blocked),
    )
    missing_admitted = max(
        0,
        MIN_ADMITTED_TRADES - len(admitted),
    )
    missing_long = max(
        0,
        MIN_DIRECTION_CLOSED_TRADES - long_closed,
    )
    missing_short = max(
        0,
        MIN_DIRECTION_CLOSED_TRADES - short_closed,
    )
    feature_integrity_clean = not missing_feature_ids
    sample_complete = (
        missing_total == 0
        and missing_blocked == 0
        and missing_admitted == 0
        and missing_long == 0
        and missing_short == 0
        and feature_integrity_clean
    )
    economics_positive = (
        candidate_pnl > ZERO
        and candidate_r > ZERO
        and delta_pnl > ZERO
        and delta_r > ZERO
    )
    robust_trade = (
        robustness.get(
            "positive_after_any_single_trade_removed"
        )
        is True
    )
    robust_market = (
        robustness.get(
            "positive_after_any_single_market_removed"
        )
        is True
    )
    ready_for_review = (
        sample_complete
        and economics_positive
        and robust_trade
        and robust_market
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "rule": state.payload()["rule"],
        "claim_scope": "prospective_closed_trade_contribution_only",
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "prospective_closed_trades": len(prospective),
        "admitted_trades": len(admitted),
        "blocked_trades": len(blocked),
        "blocked_wins": sum(
            1 for trade in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade in blocked if trade.net_pnl < ZERO
        ),
        "blocked_net_pnl": str(
            sum((trade.net_pnl for trade in blocked), ZERO)
        ),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl": str(candidate_pnl),
        "delta_net_pnl": str(delta_pnl),
        "actual_net_r": str(actual_r),
        "candidate_net_r": str(candidate_r),
        "delta_net_r": str(delta_r),
        "zero_strike_feature_evaluated": (
            zero_strike_feature_evaluated
        ),
        "nonzero_strike_bypass": nonzero_strike_bypass,
        "missing_feature_trades": len(missing_feature_ids),
        "missing_feature_trade_ids": sorted(missing_feature_ids),
        "decision_prior_strikes": {
            trade_id: prior_strikes_by_trade[trade_id]
            for trade_id in sorted(prior_strikes_by_trade)
        },
        "decision_details": {
            trade_id: decision_details[trade_id]
            for trade_id in sorted(decision_details)
        },
        "by_direction": by_direction,
        "blocked_by_market": blocked_by_market,
        "robustness": robustness,
        "readiness": {
            "ready_for_review": ready_for_review,
            "sample_complete": sample_complete,
            "feature_integrity_clean": feature_integrity_clean,
            "economics_positive": economics_positive,
            "single_trade_robust": robust_trade,
            "single_market_robust": robust_market,
            "min_prospective_closed_trades": (
                MIN_PROSPECTIVE_CLOSED_TRADES
            ),
            "min_blocked_trades": MIN_BLOCKED_TRADES,
            "min_admitted_trades": MIN_ADMITTED_TRADES,
            "min_direction_closed_trades": (
                MIN_DIRECTION_CLOSED_TRADES
            ),
            "missing_prospective_closed_trades": missing_total,
            "missing_blocked_trades": missing_blocked,
            "missing_admitted_trades": missing_admitted,
            "missing_long_closed_trades": missing_long,
            "missing_short_closed_trades": missing_short,
            "missing_feature_trades": len(missing_feature_ids),
        },
    }


def evaluate_prospective_momentum_band_entry(
    journal: JournalStore,
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveMomentumBandEntryState,
) -> dict[str, object]:
    return prospective_momentum_band_entry_summary(
        tuple(journal.iter_trades()),
        feature_store,
        state,
    )
