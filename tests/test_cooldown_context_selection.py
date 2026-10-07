from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.cooldown_context_selection import (
    CooldownContextSelectionError,
    build_cooldown_context_selection_record,
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
        "relaxed_cooldown_windows_ms": [900_000, 1_800_000, 2_700_000],
        "option_results": [
            {"timestamp_ms": 1_000},
            {"timestamp_ms": 2_000},
            {"timestamp_ms": 3_000},
        ],
    }


def _candidate(
    dimensions: tuple[str, ...],
    values: tuple[str, ...],
    *,
    validation_rows: int = 7,
    validation_markets: int = 4,
) -> dict[str, object]:
    return {
        "dimensions": dimensions,
        "values": values,
        "discovery_rows": 9,
        "discovery_markets": 5,
        "discovery_positive_share": "0.6666666666666666666666666667",
        "discovery_total_pnl": "27.5",
        "discovery_mean_return": "0.0036",
        "validation_rows": validation_rows,
        "validation_markets": validation_markets,
        "validation_positive_share": "0.8571428571428571428571428571",
        "validation_total_pnl": "11.8",
        "validation_mean_return": "0.0013",
        "validation_leave_one_option_min_pnl": "6.6",
        "validation_leave_one_market_min_pnl": "2.3",
        "validation_block_rows": (3, 4),
        "validation_block_positive_shares": (
            "0.6666666666666666666666666667",
            "1",
        ),
        "validation_block_pnl": ("3.1", "8.7"),
        "validation_blocks_consistent": 2,
        "stable_on_validation": True,
        "strategy_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }


def _stability() -> dict[str, object]:
    return {
        "source_option_count": 21,
        "settled_1h_outcomes": 21,
        "split_timestamp_ms": 2_000,
        "discovery_rows": 12,
        "validation_rows": 9,
        "candidate_count": 2,
        "stable_candidate_count": 2,
        "candidates": [
            _candidate(
                ("relaxation_window_ms", "lead_strategy", "direction"),
                ("900000", "trend", "short"),
            ),
            _candidate(
                ("relaxation_window_ms", "lead_strategy"),
                ("900000", "trend"),
            ),
        ],
        "candidate_dimension_sets": (
            ("relaxation_window_ms", "lead_strategy"),
            ("relaxation_window_ms", "lead_strategy", "direction"),
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


def test_selection_prefers_simpler_strategy_context_over_side_condition() -> None:
    record = build_cooldown_context_selection_record(
        _cooldown(),
        _stability(),
    )
    payload = record.to_dict()

    assert payload["stable_candidate_count"] == 2
    selected = payload["selected_candidate"]
    assert isinstance(selected, dict)
    assert selected["dimensions"] == (
        "relaxation_window_ms",
        "lead_strategy",
    )
    assert selected["values"] == ("900000", "trend")
    assert payload["source_max_timestamp_ms"] == 3_000
    assert payload["direction_only_candidates_allowed"] is False
    assert payload["lead_strategy_context_required"] is True
    assert payload["relaxation_window_context_required"] is True
    assert payload["window_eligible_outcomes_only"] is True
    assert payload["prospective_freeze_required_before_strategy_use"] is True
    assert payload["changes_strategy"] is False
    assert payload["changes_risk_limits"] is False
    assert payload["execution_authority"] is False
    assert len(payload["source_record_id"]) == 64


def test_selection_is_stable_but_record_binds_exact_source_order() -> None:
    first = build_cooldown_context_selection_record(
        _cooldown(),
        _stability(),
    ).to_dict()
    second_source = _stability()
    candidates = second_source["candidates"]
    assert isinstance(candidates, list)
    candidates.reverse()
    second = build_cooldown_context_selection_record(
        _cooldown(),
        second_source,
    ).to_dict()

    assert first["selected_candidate"] == second["selected_candidate"]
    assert first["stable_candidates"] == second["stable_candidates"]
    assert first["stability_source_digest"] != second["stability_source_digest"]
    assert first["source_record_id"] != second["source_record_id"]


def test_direction_only_stable_candidate_is_rejected() -> None:
    stability = _stability()
    stability["candidates"] = [
        _candidate(("direction",), ("short",)),
    ]

    with pytest.raises(
        CooldownContextSelectionError,
        match="lead_strategy context",
    ):
        build_cooldown_context_selection_record(
            _cooldown(),
            stability,
        )


def test_authority_drift_is_rejected() -> None:
    stability = deepcopy(_stability())
    stability["changes_risk_limits"] = True

    with pytest.raises(
        CooldownContextSelectionError,
        match="authority or methodology drift",
    ):
        build_cooldown_context_selection_record(
            _cooldown(),
            stability,
        )


def test_no_stable_candidate_produces_no_selection() -> None:
    stability = _stability()
    candidates = stability["candidates"]
    assert isinstance(candidates, list)
    for candidate in candidates:
        assert isinstance(candidate, dict)
        candidate["stable_on_validation"] = False

    payload = build_cooldown_context_selection_record(
        _cooldown(),
        stability,
    ).to_dict()

    assert payload["stable_candidate_count"] == 0
    assert payload["selected_candidate"] is None
    assert payload["stable_candidates"] == ()



def test_stable_candidate_without_relaxation_window_is_rejected() -> None:
    stability = _stability()
    stability["candidates"] = [
        _candidate(("lead_strategy",), ("trend",)),
    ]

    with pytest.raises(
        CooldownContextSelectionError,
        match="relaxation-window context",
    ):
        build_cooldown_context_selection_record(
            _cooldown(),
            stability,
        )
