from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_opportunity_audit import (
    CadenceOpportunityAuditError,
    load_cadence_outcomes,
)
from cocomelon.research.cadence_shadow import (
    CADENCE_SHADOW_STATE_SCHEMA_VERSION,
    FIFTEEN_MINUTES_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
    _outcome_payload,
)

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


def _write_state(
    path: Path,
    outcomes: tuple[ShadowCadenceOutcome, ...],
) -> None:
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


def test_load_cadence_outcomes_round_trips_and_sorts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cadence-shadow-state.json"
    later = _outcome(2)
    earlier = _outcome(1)
    _write_state(path, (later, earlier))

    loaded = load_cadence_outcomes(path)

    assert loaded == (earlier, later)


def test_load_cadence_outcomes_rejects_duplicate_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cadence-shadow-state.json"
    outcome = _outcome(1)
    _write_state(path, (outcome, outcome))

    with pytest.raises(
        CadenceOpportunityAuditError,
        match="DUPLICATE_OUTCOME",
    ):
        load_cadence_outcomes(path)


def test_load_cadence_outcomes_rejects_wrong_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cadence-shadow-state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "outcomes": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        CadenceOpportunityAuditError,
        match="SCHEMA_UNSUPPORTED",
    ):
        load_cadence_outcomes(path)
