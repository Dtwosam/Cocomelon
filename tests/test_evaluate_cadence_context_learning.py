from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_shadow import (
    CADENCE_SHADOW_STATE_SCHEMA_VERSION,
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
    _outcome_payload,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from scripts.evaluate_cadence_context_learning import evaluate_state


def test_context_audit_cli_reads_exact_state_and_features(
    tmp_path: Path,
) -> None:
    feature_store = LearningFeatureSnapshotStore(
        tmp_path / "learning-features"
    )
    market = MarketId("", "SOL")
    outcomes: list[ShadowCadenceOutcome] = []
    for index in range(12):
        boundary = 1_000_000 + index * FIFTEEN_MINUTES_MS
        evaluated = boundary + 1_000
        feature = FeatureSnapshot(
            market=market,
            as_of_ms=evaluated,
            source_received_at_ms=evaluated,
            schema_version=1,
            day_return=None,
            funding=Decimal("0"),
            open_interest=Decimal("1"),
            day_notional_volume=Decimal("1"),
            oi_change_fraction=None,
            funding_change=None,
            mark_oracle_dislocation_bps=None,
            return_5m=None,
            return_15m=None,
            return_1h=None,
            return_4h=None,
            realized_vol_15m=None,
            range_expansion_15m=None,
            relative_volume_15m=None,
            spread_bps=None,
            bid_depth_25bps=None,
            ask_depth_25bps=None,
            book_imbalance=None,
            book_age_ms=None,
            trend_regime=TrendRegime.UP,
            volatility_regime=VolatilityRegime.NORMAL,
            provenance=("test",),
        )
        feature_store.record(feature)
        sample = ShadowCadenceDecision(
            cadence_ms=FIFTEEN_MINUTES_MS,
            boundary_ms=boundary,
            evaluated_at_ms=evaluated,
            market=market,
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            score=Decimal("82"),
            lead_strategy="trend",
            decision_id=f"decision-{index}",
            feature_snapshot_id=feature.snapshot_id,
            entry_px=Decimal("100"),
            horizon_ms=ONE_HOUR_MS,
            target_end_ms=boundary + ONE_HOUR_MS,
            cost_fraction=Decimal("0.001"),
            off_primary_boundary=False,
        )
        outcomes.append(
            ShadowCadenceOutcome(
                sample=sample,
                exit_px=Decimal("101"),
                gross_return=Decimal("0.006"),
                net_return=Decimal("0.005"),
            )
        )

    state = tmp_path / "cadence-shadow-state.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": (
                    CADENCE_SHADOW_STATE_SCHEMA_VERSION
                ),
                "outcomes": [
                    _outcome_payload(outcome)
                    for outcome in outcomes
                ],
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_state(
        state,
        feature_store.root,
        cadence_ms=FIFTEEN_MINUTES_MS,
        horizon_ms=ONE_HOUR_MS,
    )

    assert report["research_only"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
