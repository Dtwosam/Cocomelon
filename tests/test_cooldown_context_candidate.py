from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from cocomelon.research.cooldown_context_candidate import (
    CooldownContextCandidateError,
    build_cooldown_context_candidate_freeze,
    verify_cooldown_context_candidate_freeze,
    write_cooldown_context_candidate_freeze,
)
from cocomelon.research.cooldown_context_selection import (
    build_cooldown_context_selection_record,
)
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)


def _cooldown() -> dict[str, object]:
    return {
        "candidate_id": (
            "prospective-consecutive-loss-cooldown-relaxation-v1"
        ),
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "forward_markout_only": True,
        "realized_pnl_modeled": False,
        "relaxed_cooldown_windows_ms": [900_000, 1_800_000],
        "option_results": [
            {"timestamp_ms": 1_000},
            {"timestamp_ms": 2_000},
            {"timestamp_ms": 3_000},
        ],
    }


def _candidate(
    *,
    dimensions: tuple[str, ...] = (
        "relaxation_window_ms",
        "lead_strategy",
    ),
    values: tuple[str, ...] = ("900000", "trend"),
) -> dict[str, object]:
    return {
        "dimensions": dimensions,
        "values": values,
        "discovery_rows": 10,
        "discovery_markets": 5,
        "discovery_positive_share": "0.7",
        "discovery_total_pnl": "20",
        "discovery_mean_return": "0.003",
        "validation_rows": 8,
        "validation_markets": 4,
        "validation_positive_share": "0.75",
        "validation_total_pnl": "12",
        "validation_mean_return": "0.002",
        "validation_leave_one_option_min_pnl": "7",
        "validation_leave_one_market_min_pnl": "3",
        "validation_block_rows": (4, 4),
        "validation_block_positive_shares": ("0.75", "0.75"),
        "validation_block_pnl": ("5", "7"),
        "validation_blocks_consistent": 2,
        "stable_on_validation": True,
        "strategy_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }


def _stability(
    candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    selected = _candidate() if candidate is None else candidate
    return {
        "source_option_count": 18,
        "settled_1h_outcomes": 18,
        "split_timestamp_ms": 2_000,
        "discovery_rows": 10,
        "validation_rows": 8,
        "candidate_count": 1,
        "stable_candidate_count": 1,
        "candidates": [selected],
        "candidate_dimension_sets": (
            ("relaxation_window_ms", "lead_strategy"),
        ),
        "direction_only_candidates_allowed": False,
        "lead_strategy_context_required": True,
        "relaxation_window_context_required": True,
        "window_eligible_outcomes_only": True,
        "one_hour_fee_adjusted_execution_economics_required": True,
        "chronological_holdout_required": True,
        "leave_one_option_robustness_required": True,
        "leave_one_market_robustness_required": True,
        "validation_block_consistency_required": True,
        "research_only": True,
        "descriptive_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "promotion_authority": False,
        "execution_authority": False,
        "schema_version": 2,
    }


def _selection(
    candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_cooldown_context_selection_record(
        _cooldown(),
        _stability(candidate),
    ).to_dict()


def test_freeze_binds_selected_context_and_six_hour_embargo() -> None:
    freeze = build_cooldown_context_candidate_freeze(
        _selection(),
        frozen_at_ms=10_000,
        source_paper_run_id=123,
        source_paper_run_attempt=2,
        source_paper_head_sha="a" * 40,
    )

    assert freeze.dimensions == (
        "relaxation_window_ms",
        "lead_strategy",
    )
    assert freeze.values == ("900000", "trend")
    assert freeze.relaxation_window_ms == 900_000
    assert freeze.lead_strategy == "trend"
    assert freeze.source_paper_run_id == 123
    assert freeze.source_paper_run_attempt == 2
    assert freeze.prospective_not_before_ms == (
        10_000 + MIN_PROSPECTIVE_EMBARGO_MS
    )
    assert freeze.prospective_only is True
    assert freeze.changes_strategy is False
    assert freeze.changes_risk_limits is False
    assert freeze.execution_authority is False
    assert len(freeze.candidate_id) == 64


def test_freeze_rejects_selection_identity_tampering() -> None:
    selection = _selection()
    selection["source_max_timestamp_ms"] = 999_999

    with pytest.raises(
        CooldownContextCandidateError,
        match="SELECTION_ID_MISMATCH",
    ):
        build_cooldown_context_candidate_freeze(
            selection,
            frozen_at_ms=1_000_000,
            source_paper_run_id=1,
            source_paper_run_attempt=1,
            source_paper_head_sha="b" * 40,
        )


def test_existing_freeze_is_never_replaced_by_later_selection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "freeze.json"
    first, created = write_cooldown_context_candidate_freeze(
        _selection(),
        output_path=path,
        frozen_at_ms=10_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="c" * 40,
    )
    assert created is True

    later_candidate = _candidate(
        dimensions=(
            "relaxation_window_ms",
            "lead_strategy",
            "direction",
        ),
        values=("1800000", "breakout", "short"),
    )
    second, created_again = write_cooldown_context_candidate_freeze(
        _selection(later_candidate),
        output_path=path,
        frozen_at_ms=20_000,
        source_paper_run_id=2,
        source_paper_run_attempt=1,
        source_paper_head_sha="d" * 40,
    )

    assert created_again is False
    assert second.candidate_id == first.candidate_id
    assert second.values == ("900000", "trend")
    assert verify_cooldown_context_candidate_freeze(path) == first


def test_corrupted_frozen_candidate_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "freeze.json"
    freeze, _created = write_cooldown_context_candidate_freeze(
        _selection(),
        output_path=path,
        frozen_at_ms=10_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="e" * 40,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["lead_strategy"] = "mean_reversion"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CooldownContextCandidateError):
        verify_cooldown_context_candidate_freeze(path)

    assert freeze.lead_strategy == "trend"


def test_freeze_requires_relaxation_window_and_strategy_context() -> None:
    selection = _selection()
    candidate = deepcopy(selection["selected_candidate"])
    assert isinstance(candidate, dict)
    candidate["dimensions"] = ("direction",)
    candidate["values"] = ("short",)
    selection["selected_candidate"] = candidate
    identity = {
        key: value
        for key, value in selection.items()
        if key != "source_record_id"
    }
    # Deliberately retain the old record id: any post-selection mutation fails
    # before a weaker context can be frozen.
    with pytest.raises(CooldownContextCandidateError):
        build_cooldown_context_candidate_freeze(
            selection,
            frozen_at_ms=10_000,
            source_paper_run_id=1,
            source_paper_run_attempt=1,
            source_paper_head_sha="f" * 40,
        )
