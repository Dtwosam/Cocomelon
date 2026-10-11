from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "prospective_full_stack_forward_markout",
        "prospective_momentum_band_forward_markout",
        "prospective_full_stack_capacity_reflow",
        "prospective_full_stack_exit_capacity_reflow",
    ],
)
def test_original_terminal_journal_reconstruction_has_one_shared_causal_gate(
    module_name: str,
) -> None:
    source = (
        Path("src/cocomelon/research") / f"{module_name}.py"
    ).read_text(encoding="utf-8")
    assert "terminal_trades_known_at(" in source
    assert "future_finalized_open_exposure(" in source
    assert "journal_future_close_exposure_opportunities" in source
    assert "journal_asof_provenance" in source
    assert "promotion_authority" in source
    assert '"integrity_clean"' in source


def test_asof_helpers_are_read_only_and_do_not_use_advance_knowledge() -> None:
    source = Path(
        "src/cocomelon/research/terminal_journal_asof.py"
    ).read_text(encoding="utf-8")
    assert "trade.closed_at_ms < timestamp_ms" in source
    assert "trade.closed_at_ms >= timestamp_ms" in source
    assert "trade.opened_at_ms < timestamp_ms" in source
    assert "trade.direction.value == direction" in source
    assert "trade.market.canonical == market" in source
    assert "trade.opened_at_ms >= overlap_started_at_ms" in source



@pytest.mark.parametrize(
    "module_name, witness_var",
    [
        ("first_seen_opening_witness", "trade"),
        ("opportunity_inventory_witness", "t"),
    ],
)
def test_original_overlap_witnesses_match_strict_terminal_asof_boundary(
    module_name: str, witness_var: str,
) -> None:
    source = (
        Path("src/cocomelon/research") / f"{module_name}.py"
    ).read_text(encoding="utf-8")
    assert f"{witness_var}.opened_at_ms < timestamp" in source
    assert f"{witness_var}.closed_at_ms >= timestamp" in source
    assert f"{witness_var}.market.canonical == evidence.market" in source
    assert f"{witness_var}.direction.value == evidence.direction" in source
    assert '"research_readiness_grant": False' in source
    assert '"promotion_authority": False' in source
