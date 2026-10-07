from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateError,
    build_loss_context_candidate_freeze,
    verify_loss_context_candidate_freeze,
    write_loss_context_candidate_freeze,
)
from cocomelon.research.loss_streak_context_audit import (
    LOSS_STREAK_CONTEXT_SCHEMA_VERSION,
)


def _candidate(
    *,
    dimensions: tuple[str, ...] = (
        "lead_strategy",
        "trend_regime",
    ),
    values: tuple[str, ...] = ("mean_reversion", "down"),
    validation_rows: int = 12,
    validation_markets: int = 4,
    loo_market: str = "10",
) -> dict[str, object]:
    return {
        "dimensions": dimensions,
        "values": values,
        "recurring_loss_streaks": 3,
        "discovery_rows": 14,
        "discovery_markets": 5,
        "discovery_loss_share": "0.7142857142857142857142857143",
        "discovery_filter_delta_pnl": "31",
        "validation_rows": validation_rows,
        "validation_markets": validation_markets,
        "validation_loss_share": "0.75",
        "validation_filter_delta_pnl": "22",
        "validation_leave_one_trade_min_delta_pnl": "15",
        "validation_leave_one_market_min_delta_pnl": loo_market,
        "validation_block_rows": (6, 6),
        "validation_block_loss_shares": (
            "0.6666666666666666666666666667",
            "0.8333333333333333333333333333",
        ),
        "validation_block_filter_delta_pnl": ("8", "14"),
        "validation_blocks_consistent": 2,
        "stable_on_validation": True,
        "strategy_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }


def _audit(
    candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    values = [_candidate()] if candidates is None else candidates
    return {
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "schema_version": LOSS_STREAK_CONTEXT_SCHEMA_VERSION,
        "trade_count": 40,
        "max_trade_closed_at_ms": 9_000,
        "baseline_normalization_complete": True,
        "context_filter_stability": {
            "schema_version": 1,
            "candidate_count": len(values),
            "stable_candidate_count": sum(
                item["stable_on_validation"] is True for item in values
            ),
            "candidates": values,
            "direction_only_candidates_allowed": False,
            "lead_strategy_context_required": True,
            "entry_time_context_only": True,
            "realized_net_pnl_economics_required": True,
            "chronological_holdout_required": True,
            "leave_one_trade_robustness_required": True,
            "leave_one_market_robustness_required": True,
            "validation_block_consistency_required": True,
            "prospective_freeze_required_before_strategy_use": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "promotion_authority": False,
            "execution_authority": False,
        },
    }


def test_freeze_prefers_simpler_stable_context_and_adds_embargo() -> None:
    complex_candidate = _candidate(
        dimensions=(
            "lead_strategy",
            "trend_regime",
            "direction",
        ),
        values=("mean_reversion", "down", "long"),
        validation_rows=30,
        validation_markets=8,
        loo_market="50",
    )
    freeze = build_loss_context_candidate_freeze(
        _audit([complex_candidate, _candidate()]),
        frozen_at_ms=10_000,
        source_paper_run_id=123,
        source_paper_run_attempt=2,
        source_paper_head_sha="a" * 40,
    )

    assert freeze is not None
    assert freeze.dimensions == ("lead_strategy", "trend_regime")
    assert freeze.values == ("mean_reversion", "down")
    assert freeze.prospective_not_before_ms == (
        10_000 + MIN_PROSPECTIVE_EMBARGO_MS
    )
    assert freeze.prospective_only is True
    assert freeze.changes_strategy is False
    assert freeze.changes_risk_limits is False
    assert freeze.execution_authority is False
    assert len(freeze.candidate_id) == 64


def test_no_stable_candidate_produces_no_freeze() -> None:
    candidate = _candidate()
    candidate["stable_on_validation"] = False

    freeze = build_loss_context_candidate_freeze(
        _audit([candidate]),
        frozen_at_ms=10_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="b" * 40,
    )

    assert freeze is None


def test_direction_only_candidate_is_rejected() -> None:
    candidate = _candidate(
        dimensions=("direction",),
        values=("long",),
    )

    with pytest.raises(
        LossContextCandidateError,
        match="DIRECTION_ONLY_FORBIDDEN",
    ):
        build_loss_context_candidate_freeze(
            _audit([candidate]),
            frozen_at_ms=10_000,
            source_paper_run_id=1,
            source_paper_run_attempt=1,
            source_paper_head_sha="c" * 40,
        )


def test_incomplete_baseline_cannot_be_frozen() -> None:
    audit = _audit()
    audit["baseline_normalization_complete"] = False

    with pytest.raises(
        LossContextCandidateError,
        match="BASELINE_INCOMPLETE",
    ):
        build_loss_context_candidate_freeze(
            audit,
            frozen_at_ms=10_000,
            source_paper_run_id=1,
            source_paper_run_attempt=1,
            source_paper_head_sha="d" * 40,
        )


def test_existing_freeze_is_immutable_and_corruption_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "freeze.json"
    first, created = write_loss_context_candidate_freeze(
        _audit(),
        output_path=path,
        frozen_at_ms=10_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="e" * 40,
    )
    assert first is not None
    assert created is True

    later = _candidate(
        dimensions=("lead_strategy", "volatility_regime"),
        values=("trend", "high"),
        validation_rows=50,
        validation_markets=10,
        loo_market="100",
    )
    second, created_again = write_loss_context_candidate_freeze(
        _audit([later]),
        output_path=path,
        frozen_at_ms=20_000,
        source_paper_run_id=2,
        source_paper_run_attempt=1,
        source_paper_head_sha="f" * 40,
    )
    assert second == first
    assert created_again is False

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["values"] = ["mean_reversion", "up"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LossContextCandidateError):
        verify_loss_context_candidate_freeze(path)


def test_authority_drift_is_rejected() -> None:
    audit = deepcopy(_audit())
    audit["changes_strategy"] = True

    with pytest.raises(
        LossContextCandidateError,
        match="AUTHORITY_INVALID",
    ):
        build_loss_context_candidate_freeze(
            audit,
            frozen_at_ms=10_000,
            source_paper_run_id=1,
            source_paper_run_attempt=1,
            source_paper_head_sha="1" * 40,
        )
