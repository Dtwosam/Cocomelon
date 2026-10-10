"""Fixed new-paper-exposure intervention, never a retrospective profit claim."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.epochs import EpochMarketEvaluation
from cocomelon.research.paper_ena_quarantine import (
    ACTIVE_FROM_MS,
    ACTIVE_UNTIL_MS,
    BLOCK_REASON,
    FREEZE_AT_MS,
    MARKET_CANONICAL,
    SOURCE_AUDIT_MEMBER_SHA256,
    SOURCE_LAST_CLOSED_AT_MS,
    PaperEnaQuarantine,
)


def _candidate(
    market: MarketId, direction: Direction, decision_id: str = "d1",
    *, timestamp_ms: int = ACTIVE_FROM_MS,
) -> EpochMarketEvaluation:
    return cast(
        EpochMarketEvaluation,
        SimpleNamespace(
            decision=SimpleNamespace(
                market=market,
                direction=direction,
                decision_id=decision_id,
                timestamp_ms=timestamp_ms,
            ),
        ),
    )


def test_quarantine_is_immutable_time_bounded_and_post_discovery() -> None:
    assert SOURCE_LAST_CLOSED_AT_MS < FREEZE_AT_MS
    assert ACTIVE_FROM_MS - FREEZE_AT_MS == 6 * 60 * 60 * 1000
    assert ACTIVE_UNTIL_MS - ACTIVE_FROM_MS == 7 * 24 * 60 * 60 * 1000
    assert len(SOURCE_AUDIT_MEMBER_SHA256) == 64
    assert MARKET_CANONICAL == "ENA"


@pytest.mark.parametrize("side", [Direction.LONG, Direction.SHORT])
def test_only_forward_original_ena_openings_are_blocked(side: Direction) -> None:
    policy = PaperEnaQuarantine()
    entry = _candidate(MarketId("", "ENA"), side)
    assert (
        policy.block_reason(entry, attempt_timestamp_ms=ACTIVE_FROM_MS - 1)
        is None
    )
    assert (
        policy.block_reason(entry, attempt_timestamp_ms=ACTIVE_FROM_MS)
        == BLOCK_REASON
    )
    assert (
        policy.block_reason(entry, attempt_timestamp_ms=ACTIVE_UNTIL_MS - 1)
        == BLOCK_REASON
    )
    assert (
        policy.block_reason(entry, attempt_timestamp_ms=ACTIVE_UNTIL_MS)
        is None
    )
    assert policy.blocked_decisions == 1
    assert policy.blocked_by_side == {side.value: 1}



def test_past_decision_cannot_be_selected_by_later_paper_ioc() -> None:
    policy = PaperEnaQuarantine()
    decision = _candidate(
        MarketId("", "ENA"), Direction.SHORT,
        timestamp_ms=ACTIVE_FROM_MS - 1,
    )
    assert (
        policy.block_reason(
            decision, attempt_timestamp_ms=ACTIVE_FROM_MS + 1000
        )
        is None
    )
    assert policy.blocked_decisions == 0

def test_other_markets_and_dex_scopes_are_never_blocked() -> None:
    policy = PaperEnaQuarantine()
    for name in ("BTC", "ETH", "ARB", "ENA"):
        market = (
            MarketId("otherdex", "ENA")
            if name == "ENA"
            else MarketId("", name)
        )
        for side in (Direction.LONG, Direction.SHORT):
            assert (
                policy.block_reason(
                    _candidate(market, side),
                    attempt_timestamp_ms=ACTIVE_FROM_MS,
                )
                is None
            )
    assert policy.blocked_decisions == 0


def test_no_trade_is_not_an_entry_and_does_not_count() -> None:
    policy = PaperEnaQuarantine()
    assert (
        policy.block_reason(
            _candidate(MarketId("", "ENA"), Direction.NO_TRADE),
            attempt_timestamp_ms=ACTIVE_FROM_MS,
        )
        is None
    )
    assert policy.blocked_decisions == 0


def test_distinct_decisions_count_once_and_do_not_claim_avoided_profit() -> None:
    policy = PaperEnaQuarantine()
    for index in range(3):
        decision = _candidate(
            MarketId("", "ENA"),
            Direction.LONG if index != 2 else Direction.SHORT,
            decision_id=f"opening-{index}",
        )
        assert (
            policy.block_reason(decision, attempt_timestamp_ms=ACTIVE_FROM_MS)
            == BLOCK_REASON
        )
        assert (
            policy.block_reason(decision, attempt_timestamp_ms=ACTIVE_FROM_MS)
            == BLOCK_REASON
        )
    summary = policy.summary()
    assert summary["blocked_decisions_this_worker"] == 3
    assert summary["blocked_by_side_this_worker"] == {
        "long": 2, "short": 1,
    }
    assert summary["source_ena_closed_trades"] == 16
    assert summary["source_ena_winners"] == 0
    assert summary["source_ena_booked_net_pnl"].startswith("-165.4427")
    assert summary["paper_only"] is True
    assert summary["existing_positions_and_exits_untouched"] is True
    assert summary["risk_limits_unchanged"] is True
    assert summary["live_orders_enabled"] is False
    assert summary["retrospectively_selected"] is True
    assert summary["profitable_edge_verified"] is False
    assert summary["matched_forward_baseline_available"] is False


def test_quarantine_wired_only_to_original_paper_opening_not_paired_control() -> None:
    from pathlib import Path

    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    assert source.count("paper_ena_quarantine = PaperEnaQuarantine()") == 1
    assert source.count("opening_candidate_filter=paper_ena_quarantine") == 1
    assert source.count('root / "paper-ena-quarantine-summary.json"') == 1
    assert "loss_context_paired_shadow_runtime" in source
    paired = Path(
        "src/cocomelon/research/loss_context_paired_portfolio_shadow.py"
    ).read_text(encoding="utf-8")
    assert "PaperEnaQuarantine" not in paired
    assert "opening_candidate_filter=self._baseline_filter" in paired
    assert "opening_candidate_filter=self._candidate_filter" in paired

    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    after_handoff = workflow.index(
        "- name: Upload fixed ENA paper quarantine decision receipt"
    )
    durable = workflow.index("- name: Upload durable continuous paper state")
    compact = workflow.index(
        "- name: Verify compact exact LONG trend research source"
    )
    assert durable < after_handoff < compact
    block = workflow[after_handoff:compact]
    assert "continue-on-error: true" in block
    assert "steps.fast_resume_dispatch.outcome == 'success'" in block
    assert "steps.fallback_resume_dispatch.outcome == 'success'" in block
    assert "paper-ena-quarantine-summary.json" in block
    assert "continuous-paper-ena-quarantine-" in block
