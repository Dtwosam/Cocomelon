"""Pin live PAPER research-startup attribution without changing economic gates."""
from __future__ import annotations

import ast
from pathlib import Path

from scripts.render_continuous_paper_live_status import _startup_profile_line


def test_expensive_research_restore_stages_have_real_start_stop_witnesses() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    ast.parse(source)
    cohort_pairs = {
        "original_rank_source_restore": "rank_source_started",
        "exit_shadow_restore": "exit_shadow_started",
        "shadow_position_reconcile": "shadow_reconcile_started",
        "candidate_state_restore": "candidate_restore_started",
    }
    for key, started_var in cohort_pairs.items():
        assert source.count(f'{started_var} = time.perf_counter()') == 1
        assert source.count(
            f'record_startup_component("{key}", {started_var})'
        ) == 1
    assert 'record_startup_component(\n        "research_state_restore",' in source
    assert 'startup_component_ms["pre_monitor_total"]' in source


def test_original_research_bottleneck_is_visible_without_profit_claim() -> None:
    status = _startup_profile_line({
        "pre_monitor_total": 1_682_506,
        "research_state_restore": 1_669_717,
        "original_rank_source_restore": 1_660_000,
        "exit_shadow_restore": 5_000,
        "shadow_position_reconcile": 1_000,
        "candidate_state_restore": 2_000,
        "execution_restore": 10,
    })
    assert "original_rank_source_restore=1660000ms" in status
    assert "candidate_state_restore=2000ms" in status
    assert "exit_shadow_restore=5000ms" in status
    assert "shadow_position_reconcile=1000ms" not in status  # top five only
    assert "profit" not in status.lower() or "non-PnL" in status


def test_research_profile_is_not_evidence_of_source_or_account_profit() -> None:
    value = _startup_profile_line({
        "pre_monitor_total": 1_000,
        "original_rank_source_restore": 900,
        "source_certified": True,
        "profitability_confirmed": False,
    })
    assert "original_rank_source_restore=900ms" in value
    assert "source_certified" not in value
    assert "profitability_confirmed" not in value
