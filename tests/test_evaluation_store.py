import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import (
    AccountEquityFact,
    DecisionEvaluationFact,
    EquityFactKind,
)
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationConsistencyError, EvaluationFactStore

MARKET = MarketId("", "SOL")


def decision_fact(
    *,
    decision_id: str = "strategy-1",
    timestamp_ms: int = 1_000,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=decision_id,
        feature_snapshot_id=f"feature-{decision_id}",
        replay_run_id="run-1",
        market=MARKET,
        direction=Direction.LONG,
        timestamp_ms=timestamp_ms,
        score=Decimal("70"),
        lead_strategy="trend",
        signal_ids=(f"signal-{decision_id}",),
        reason_codes=("TREND_UP",),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def equity_fact(
    *,
    state_id: str = "state-1",
    timestamp_ms: int = 1_000,
) -> AccountEquityFact:
    return AccountEquityFact(
        replay_run_id="run-1",
        account_state_id=state_id,
        timestamp_ms=timestamp_ms,
        kind=EquityFactKind.MARK,
        equity=Decimal("10000"),
        cash=Decimal("10000"),
        unrealized_pnl=Decimal("0"),
        realized_gross_pnl=Decimal("0"),
        cumulative_fees=Decimal("0"),
        cumulative_funding=Decimal("0"),
        gross_open_notional=Decimal("0"),
        open_position_count=0,
    )


def test_schema_contains_phase9_fact_and_manifest_tables(tmp_path: Path) -> None:
    path = tmp_path / "evaluation.sqlite3"
    store = EvaluationFactStore(path)
    store.close()

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "evaluation_decision_facts",
        "evaluation_equity_facts",
        "evaluation_dataset_manifests",
        "evaluation_split_manifests",
        "evaluation_candidate_sets",
        "evaluation_oos_consumptions",
        "evaluation_results",
    } <= tables


def test_decision_fact_retry_is_idempotent_and_restart_safe(tmp_path: Path) -> None:
    path = tmp_path / "evaluation.sqlite3"
    item = decision_fact()
    store = EvaluationFactStore(path)
    store.record_decision_fact(item)
    store.record_decision_fact(item)
    store.close()

    reopened = EvaluationFactStore(path)
    assert reopened.load_decision_fact(item.fact_id) == item
    assert reopened.load_decision_by_strategy_id(item.strategy_decision_id, "run-1") == item
    reopened.close()


def test_equity_fact_round_trips_and_run_filter_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "evaluation.sqlite3"
    later = equity_fact(state_id="state-2", timestamp_ms=2_000)
    earlier = equity_fact(state_id="state-1", timestamp_ms=1_000)
    store = EvaluationFactStore(path)
    store.record_equity_fact(later)
    store.record_equity_fact(earlier)
    store.close()

    reopened = EvaluationFactStore(path)
    assert tuple(reopened.iter_equity_facts("run-1")) == (earlier, later)
    reopened.close()


def test_decision_fact_iteration_is_chronological_then_id(tmp_path: Path) -> None:
    path = tmp_path / "evaluation.sqlite3"
    later = decision_fact(decision_id="strategy-2", timestamp_ms=2_000)
    earlier = decision_fact(decision_id="strategy-1", timestamp_ms=1_000)
    store = EvaluationFactStore(path)
    store.record_decision_fact(later)
    store.record_decision_fact(earlier)

    assert tuple(store.iter_decision_facts()) == (earlier, later)
    store.close()


def test_conflicting_decision_fact_payload_fails_closed(tmp_path: Path) -> None:
    store = EvaluationFactStore(tmp_path / "evaluation.sqlite3")
    item = decision_fact()
    store.record_decision_fact(item)

    with store.connection:
        store.connection.execute(
            "UPDATE evaluation_decision_facts SET payload_json = ? WHERE fact_id = ?",
            ('{"corrupt":true}', item.fact_id),
        )

    with pytest.raises(EvaluationConsistencyError, match="conflicting"):
        store.record_decision_fact(item)
    store.close()


def test_failed_fact_write_rolls_back(tmp_path: Path) -> None:
    store = EvaluationFactStore(tmp_path / "evaluation.sqlite3")
    item = decision_fact()

    def fail_after_primary() -> None:
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        store._record_decision_fact_transaction(item, after_primary=fail_after_primary)

    assert store.load_decision_fact(item.fact_id) is None
    store.close()
