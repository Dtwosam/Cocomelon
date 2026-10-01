from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_RULES,
)
from cocomelon.research.profit_lock_execution_ledger import (
    validate_profit_lock_execution_ledger,
)
from cocomelon.research.profit_lock_execution_readiness import (
    MIN_ACTIVATED_TRADES_PER_RULE,
    MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE,
    MIN_SIMULATED_FULL_CLOSES_PER_RULE,
    MIN_TRIGGERED_TRADES_PER_RULE,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)

STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-breakeven-after-0_5r-v1"
RULE_ID: Final = "breakeven_after_0_5r"
ACTIVATE_AT_R: Final = Decimal("0.5")
LOCK_AT_R: Final = Decimal("0")
EMBARGO_MS: Final = 6 * 60 * 60 * 1_000
MIN_DIRECTION_EVALUATED_TRADES: Final = 5
ZERO: Final = Decimal("0")


class ProspectiveBreakevenProfitLockError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveBreakevenProfitLockState:
    frozen_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError(
                "unsupported prospective breakeven state schema"
            )
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError(
                "unsupported prospective breakeven candidate"
            )

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
                "rule_id": RULE_ID,
                "activate_at_r": str(ACTIVATE_AT_R),
                "lock_at_r": str(LOCK_AT_R),
                "action": "tighten_stop_to_breakeven_once",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveBreakevenProfitLockState:
        if not isinstance(raw, Mapping):
            raise ProspectiveBreakevenProfitLockError(
                "prospective breakeven state must be an object"
            )
        expected_rule = {
            "rule_id": RULE_ID,
            "activate_at_r": str(ACTIVATE_AT_R),
            "lock_at_r": str(LOCK_AT_R),
            "action": "tighten_stop_to_breakeven_once",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveBreakevenProfitLockError(
                "prospective breakeven rule drift"
            )
        if raw.get("embargo_ms") != EMBARGO_MS:
            raise ProspectiveBreakevenProfitLockError(
                "prospective breakeven embargo drift"
            )
        schema_version = raw.get("schema_version")
        frozen_at_ms = raw.get("frozen_at_ms")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectiveBreakevenProfitLockError(
                "schema_version must be an integer"
            )
        if isinstance(frozen_at_ms, bool) or not isinstance(
            frozen_at_ms,
            int,
        ):
            raise ProspectiveBreakevenProfitLockError(
                "frozen_at_ms must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectiveBreakevenProfitLockError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise ProspectiveBreakevenProfitLockError(
                "candidate_id must be a string"
            )
        try:
            state = cls(
                frozen_at_ms=frozen_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise ProspectiveBreakevenProfitLockError(
                str(exc)
            ) from exc
        if state.started_at_ms != started_at_ms:
            raise ProspectiveBreakevenProfitLockError(
                "started_at_ms does not match frozen embargo"
            )
        return state


def _expected_rules() -> list[dict[str, str]]:
    return [
        {
            "rule_id": rule.rule_id,
            "activate_at_r": str(rule.activate_at_r),
            "lock_at_r": str(rule.lock_at_r),
        }
        for rule in DEFAULT_PROFIT_LOCK_RULES
    ]


def _robustness(
    pairs: tuple[tuple[TradeJournalEntry, ProfitLockExecutionOutcome], ...],
) -> dict[str, object]:
    pnl_deltas = tuple(
        outcome.delta_net_pnl_estimate
        for _trade, outcome in pairs
        if outcome.delta_net_pnl_estimate is not None
    )
    r_deltas = tuple(
        outcome.delta_net_r_estimate
        for _trade, outcome in pairs
        if outcome.delta_net_r_estimate is not None
    )
    if len(pnl_deltas) != len(r_deltas):
        raise ProspectiveBreakevenProfitLockError(
            "prospective economic delta coverage mismatch"
        )
    total_pnl = sum(pnl_deltas, ZERO)
    total_r = sum(r_deltas, ZERO)
    leave_trade_pnl = tuple(
        total_pnl - value for value in pnl_deltas
    )
    leave_trade_r = tuple(total_r - value for value in r_deltas)

    market_pnl: dict[str, Decimal] = {}
    market_r: dict[str, Decimal] = {}
    for (trade, _outcome), pnl_delta, r_delta in zip(
        pairs,
        pnl_deltas,
        r_deltas,
        strict=True,
    ):
        market = trade.market.canonical
        market_pnl[market] = market_pnl.get(market, ZERO) + pnl_delta
        market_r[market] = market_r.get(market, ZERO) + r_delta
    leave_market_pnl = tuple(
        total_pnl - value for value in market_pnl.values()
    )
    leave_market_r = tuple(
        total_r - value for value in market_r.values()
    )
    return {
        "evaluated_trades": len(pnl_deltas),
        "market_count": len(market_pnl),
        "delta_net_pnl": str(total_pnl),
        "delta_net_r": str(total_r),
        "leave_one_trade_out_min_delta_pnl": str(
            min(leave_trade_pnl, default=ZERO)
        ),
        "leave_one_trade_out_min_delta_r": str(
            min(leave_trade_r, default=ZERO)
        ),
        "positive_after_removing_any_one_trade": (
            len(pnl_deltas) >= 2
            and min(leave_trade_pnl, default=ZERO) > ZERO
            and min(leave_trade_r, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_delta_pnl": str(
            min(leave_market_pnl, default=ZERO)
        ),
        "leave_one_market_out_min_delta_r": str(
            min(leave_market_r, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(market_pnl) >= 2
            and min(leave_market_pnl, default=ZERO) > ZERO
            and min(leave_market_r, default=ZERO) > ZERO
        ),
    }


def prospective_breakeven_profit_lock_summary(
    trades: Sequence[TradeJournalEntry],
    execution_shadow_state: object,
    state: ProspectiveBreakevenProfitLockState,
) -> dict[str, object]:
    if not isinstance(execution_shadow_state, Mapping):
        raise ProspectiveBreakevenProfitLockError(
            "execution shadow state must be an object"
        )
    if execution_shadow_state.get("schema_version") != (
        EXECUTION_SHADOW_STATE_SCHEMA_VERSION
    ):
        raise ProspectiveBreakevenProfitLockError(
            "execution shadow state schema mismatch"
        )
    if execution_shadow_state.get("rules") != _expected_rules():
        raise ProspectiveBreakevenProfitLockError(
            "execution shadow rule drift"
        )

    values = tuple(trades)
    trade_by_id = {trade.trade_id: trade for trade in values}
    if len(trade_by_id) != len(values):
        raise ProspectiveBreakevenProfitLockError(
            "journal contains duplicate trade ids"
        )
    prospective_trades = tuple(
        trade
        for trade in values
        if trade.opened_at_ms >= state.started_at_ms
    )
    prospective_ids = {trade.trade_id for trade in prospective_trades}

    raw_outcomes = execution_shadow_state.get("outcomes")
    if not isinstance(raw_outcomes, Sequence) or isinstance(
        raw_outcomes,
        (str, bytes),
    ):
        raise ProspectiveBreakevenProfitLockError(
            "execution shadow outcomes must be an array"
        )
    outcomes = tuple(
        ProfitLockExecutionOutcome.from_payload(raw)
        for raw in raw_outcomes
    )
    selected = tuple(
        outcome
        for outcome in outcomes
        if outcome.rule_id == RULE_ID
        and outcome.trade_id in prospective_ids
    )
    selected_ids = tuple(outcome.trade_id for outcome in selected)
    if len(selected_ids) != len(set(selected_ids)):
        raise ProspectiveBreakevenProfitLockError(
            "prospective breakeven outcomes contain duplicate trade ids"
        )

    outcome_by_id = {outcome.trade_id: outcome for outcome in selected}
    missing_trade_ids = tuple(
        sorted(prospective_ids - set(outcome_by_id))
    )
    orphan_trade_ids = tuple(
        sorted(
            outcome.trade_id
            for outcome in outcomes
            if outcome.rule_id == RULE_ID
            and outcome.trade_id not in trade_by_id
        )
    )
    pairs: list[
        tuple[TradeJournalEntry, ProfitLockExecutionOutcome]
    ] = []
    for trade in prospective_trades:
        outcome = outcome_by_id.get(trade.trade_id)
        if outcome is None:
            continue
        if (
            outcome.opening_plan_id != trade.opening_plan_id
            or outcome.market != trade.market.canonical
            or outcome.direction != trade.direction.value
            or outcome.actual_net_pnl != trade.net_pnl
            or outcome.actual_net_r != trade.net_r
        ):
            raise ProspectiveBreakevenProfitLockError(
                "prospective breakeven outcome journal drift"
            )
        pairs.append((trade, outcome))
    resolved_pairs = tuple(pairs)

    evaluated = tuple(
        pair
        for pair in resolved_pairs
        if pair[1].candidate_net_pnl_estimate is not None
    )
    actual_pnl = sum(
        (outcome.actual_net_pnl for _trade, outcome in evaluated),
        ZERO,
    )
    candidate_pnl = sum(
        (
            outcome.candidate_net_pnl_estimate
            for _trade, outcome in evaluated
            if outcome.candidate_net_pnl_estimate is not None
        ),
        ZERO,
    )
    actual_r = sum(
        (outcome.actual_net_r for _trade, outcome in evaluated),
        ZERO,
    )
    candidate_r = sum(
        (
            outcome.candidate_net_r_estimate
            for _trade, outcome in evaluated
            if outcome.candidate_net_r_estimate is not None
        ),
        ZERO,
    )
    activated = sum(
        outcome.activated for _trade, outcome in resolved_pairs
    )
    triggered = sum(
        outcome.triggered for _trade, outcome in resolved_pairs
    )
    full_closes = sum(
        outcome.simulated_close_complete
        for _trade, outcome in resolved_pairs
    )
    triggered_incomplete = sum(
        outcome.candidate_source == "triggered_incomplete"
        for _trade, outcome in resolved_pairs
    )
    long_evaluated = sum(
        trade.direction.value == "long" for trade, _outcome in evaluated
    )
    short_evaluated = sum(
        trade.direction.value == "short"
        for trade, _outcome in evaluated
    )
    robustness = _robustness(evaluated)

    lineage_mismatch = execution_shadow_state.get(
        "lineage_mismatch_closed_trades",
        0,
    )
    orphaned_restored = execution_shadow_state.get(
        "orphaned_restored_positions",
        0,
    )
    if (
        isinstance(lineage_mismatch, bool)
        or not isinstance(lineage_mismatch, int)
        or lineage_mismatch < 0
        or isinstance(orphaned_restored, bool)
        or not isinstance(orphaned_restored, int)
        or orphaned_restored < 0
    ):
        raise ProspectiveBreakevenProfitLockError(
            "execution shadow integrity counters are invalid"
        )
    integrity_clean = (
        not missing_trade_ids
        and not orphan_trade_ids
        and lineage_mismatch == 0
        and orphaned_restored == 0
        and triggered_incomplete == 0
    )

    missing_evaluated = max(
        0,
        MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE - len(evaluated),
    )
    missing_activated = max(
        0,
        MIN_ACTIVATED_TRADES_PER_RULE - activated,
    )
    missing_triggered = max(
        0,
        MIN_TRIGGERED_TRADES_PER_RULE - triggered,
    )
    missing_full = max(
        0,
        MIN_SIMULATED_FULL_CLOSES_PER_RULE - full_closes,
    )
    missing_long = max(
        0,
        MIN_DIRECTION_EVALUATED_TRADES - long_evaluated,
    )
    missing_short = max(
        0,
        MIN_DIRECTION_EVALUATED_TRADES - short_evaluated,
    )
    sample_complete = (
        missing_evaluated == 0
        and missing_activated == 0
        and missing_triggered == 0
        and missing_full == 0
        and missing_long == 0
        and missing_short == 0
    )
    candidate_profitable = candidate_pnl > ZERO and candidate_r > ZERO
    delta_positive = (
        candidate_pnl - actual_pnl > ZERO
        and candidate_r - actual_r > ZERO
    )
    trade_robust = (
        robustness["positive_after_removing_any_one_trade"] is True
    )
    market_robust = (
        robustness["positive_after_removing_any_one_market"] is True
    )
    ready = (
        integrity_clean
        and sample_complete
        and candidate_profitable
        and delta_positive
        and trade_robust
        and market_robust
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
        "prospective_closed_trades": len(prospective_trades),
        "matched_outcomes": len(resolved_pairs),
        "economically_evaluated_trades": len(evaluated),
        "activated_trades": activated,
        "triggered_trades": triggered,
        "simulated_full_closes": full_closes,
        "triggered_incomplete": triggered_incomplete,
        "long_evaluated_trades": long_evaluated,
        "short_evaluated_trades": short_evaluated,
        "missing_outcome_trade_ids": list(missing_trade_ids),
        "orphan_outcome_trade_ids": list(orphan_trade_ids),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl": str(candidate_pnl),
        "delta_net_pnl": str(candidate_pnl - actual_pnl),
        "actual_net_r": str(actual_r),
        "candidate_net_r": str(candidate_r),
        "delta_net_r": str(candidate_r - actual_r),
        "robustness": robustness,
        "readiness": {
            "ready_for_review": ready,
            "integrity_clean": integrity_clean,
            "sample_complete": sample_complete,
            "candidate_profitable": candidate_profitable,
            "delta_positive": delta_positive,
            "single_trade_robust": trade_robust,
            "single_market_robust": market_robust,
            "min_economically_evaluated_trades": (
                MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE
            ),
            "min_activated_trades": MIN_ACTIVATED_TRADES_PER_RULE,
            "min_triggered_trades": MIN_TRIGGERED_TRADES_PER_RULE,
            "min_simulated_full_closes": (
                MIN_SIMULATED_FULL_CLOSES_PER_RULE
            ),
            "min_direction_evaluated_trades": (
                MIN_DIRECTION_EVALUATED_TRADES
            ),
            "missing_evaluated_trades": missing_evaluated,
            "missing_activated_trades": missing_activated,
            "missing_triggered_trades": missing_triggered,
            "missing_simulated_full_closes": missing_full,
            "missing_long_evaluated_trades": missing_long,
            "missing_short_evaluated_trades": missing_short,
        },
    }



def prospective_breakeven_from_execution_ledger(
    trades: Sequence[TradeJournalEntry],
    execution_ledger: object,
    state: ProspectiveBreakevenProfitLockState,
) -> dict[str, object]:
    validated = validate_profit_lock_execution_ledger(
        execution_ledger
    )
    candidate = validated.get("candidate")
    integrity = validated.get("integrity_counters")
    rows = validated.get("rows")
    if not isinstance(candidate, Mapping):
        raise ProspectiveBreakevenProfitLockError(
            "execution ledger candidate metadata is invalid"
        )
    if not isinstance(integrity, Mapping):
        raise ProspectiveBreakevenProfitLockError(
            "execution ledger integrity counters are invalid"
        )
    if not isinstance(rows, tuple):
        raise ProspectiveBreakevenProfitLockError(
            "execution ledger rows are invalid"
        )

    shadow_state = {
        "schema_version": candidate.get(
            "state_schema_version"
        ),
        "started_at_ms": candidate.get("started_at_ms"),
        "execution_config": candidate.get("execution_config"),
        "rules": candidate.get("rules"),
        "positions": [],
        "outcomes": list(rows),
        "excluded_closed_trades": integrity.get(
            "excluded_closed_trades",
            0,
        ),
        "lineage_mismatch_closed_trades": integrity.get(
            "lineage_mismatch_closed_trades",
            0,
        ),
        "orphaned_restored_positions": integrity.get(
            "orphaned_restored_positions",
            0,
        ),
    }
    result = prospective_breakeven_profit_lock_summary(
        trades,
        shadow_state,
        state,
    )
    result = dict(result)
    result["source_execution_ledger_sha256"] = validated.get(
        "ledger_sha256"
    )
    result["source_execution_ledger_row_count"] = validated.get(
        "row_count"
    )
    source_history = validated.get("source_history")
    if isinstance(source_history, list) and source_history:
        latest = source_history[-1]
        if isinstance(latest, Mapping):
            result["source_paper_run_id"] = latest.get(
                "source_paper_run_id"
            )
            result["source_paper_run_attempt"] = latest.get(
                "source_paper_run_attempt"
            )
            result["source_artifact_name"] = latest.get(
                "source_artifact_name"
            )
            result["source_artifact_digest"] = latest.get(
                "source_artifact_digest"
            )
    return result
