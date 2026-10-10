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
    assert "trade.closed_at_ms <= timestamp_ms" in source
    assert "trade.closed_at_ms > timestamp_ms" in source
    assert "trade.opened_at_ms < timestamp_ms" in source
    assert "trade.direction.value == direction" in source
    assert "trade.market.canonical == market" in source
    assert "trade.opened_at_ms >= overlap_started_at_ms" in source
