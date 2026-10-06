from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_decision_export import (
    export_continuous_paper_decision_facts,
)
from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)


def _fact(
    *,
    suffix: str,
    replay_run_id: str,
    direction: Direction,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=f"strategy-{suffix}",
        feature_snapshot_id=f"feature-{suffix}",
        replay_run_id=replay_run_id,
        market=MarketId("", "HYPE"),
        direction=direction,
        timestamp_ms=1_000,
        score=Decimal("0") if direction is Direction.NO_TRADE else Decimal("70"),
        lead_strategy=None if direction is Direction.NO_TRADE else "trend",
        signal_ids=() if direction is Direction.NO_TRADE else (f"signal-{suffix}",),
        reason_codes=("NO_SIGNAL",) if direction is Direction.NO_TRADE else ("TREND",),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def test_compact_decision_store_is_idempotent_and_verified(tmp_path: Path) -> None:
    store = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    fact = _fact(
        suffix="a",
        replay_run_id="continuous-paper-mainnet-v1",
        direction=Direction.NO_TRADE,
    )

    assert store.record(fact) is True
    assert store.record(fact) is False

    verified = store.load(fact.fact_id)
    assert verified is not None
    assert verified.fact == fact
    assert len(verified.record_sha256) == 64
    assert tuple(item.fact for item in store.iter_verified()) == (fact,)
    assert len(store.state_digest) == 64


def test_export_filters_replay_run_and_is_restart_safe(tmp_path: Path) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    output = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    try:
        selected = (
            _fact(
                suffix="long",
                replay_run_id="continuous-paper-mainnet-v1",
                direction=Direction.LONG,
            ),
            _fact(
                suffix="skip",
                replay_run_id="continuous-paper-mainnet-v1",
                direction=Direction.NO_TRADE,
            ),
        )
        other = _fact(
            suffix="other",
            replay_run_id="other-run",
            direction=Direction.SHORT,
        )
        facts.record_decision_facts((*selected, other))

        first = export_continuous_paper_decision_facts(
            facts,
            output,
            replay_run_id="continuous-paper-mainnet-v1",
        )
        second = export_continuous_paper_decision_facts(
            facts,
            output,
            replay_run_id="continuous-paper-mainnet-v1",
        )
    finally:
        facts.close()

    assert first.scanned_facts == 3
    assert first.selected_facts == 2
    assert first.created_records == 2
    assert first.long_decisions == 1
    assert first.short_decisions == 0
    assert first.no_trade_decisions == 1
    assert second.created_records == 0
    assert second.state_digest == first.state_digest
    assert tuple(item.fact for item in output.iter_verified()) == selected
