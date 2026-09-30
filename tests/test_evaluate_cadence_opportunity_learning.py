from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_shadow import (
    CADENCE_SHADOW_STATE_SCHEMA_VERSION,
    FIFTEEN_MINUTES_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
    _outcome_payload,
)
from scripts.evaluate_cadence_opportunity_learning import evaluate_state

MARKET = MarketId("", "SOL")


def _outcome(index: int) -> ShadowCadenceOutcome:
    boundary = 1_000_000 + index * FIFTEEN_MINUTES_MS
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=boundary + 1_000,
        market=MARKET,
        direction=(
            Direction.LONG
            if index % 2 == 0
            else Direction.SHORT
        ),
        score=Decimal("82"),
        lead_strategy="trend",
        decision_id=f"decision-{index}",
        feature_snapshot_id=f"feature-{index}",
        entry_px=Decimal("100"),
        horizon_ms=FIFTEEN_MINUTES_MS,
        target_end_ms=boundary + FIFTEEN_MINUTES_MS,
        cost_fraction=Decimal("0.001"),
        off_primary_boundary=False,
    )
    return ShadowCadenceOutcome(
        sample=sample,
        exit_px=Decimal("101"),
        gross_return=Decimal("0.011"),
        net_return=Decimal("0.01"),
    )


def test_evaluate_state_reads_exact_durable_cadence_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cadence-shadow-state.json"
    outcomes = tuple(_outcome(index) for index in range(20))
    path.write_text(
        json.dumps(
            {
                "schema_version": CADENCE_SHADOW_STATE_SCHEMA_VERSION,
                "outcomes": [
                    _outcome_payload(outcome)
                    for outcome in outcomes
                ],
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_state(path)

    assert report["research_only"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["settled_outcomes"] == 20
