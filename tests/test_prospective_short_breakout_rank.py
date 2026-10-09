from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research import prospective_short_breakout_rank as research


def _trade(
    identity: str,
    *,
    opened: int,
    side: Direction = Direction.SHORT,
    pnl: str = "-5",
    coin: str = "BTC",
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=identity,
        opened_at_ms=opened,
        closed_at_ms=opened + 100,
        direction=side,
        market=MarketId("", coin),
        net_pnl=Decimal(pnl),
        net_r=Decimal(pnl) / Decimal("10"),
    )


def _context(rank: int, *, lead: str = "breakout") -> dict[str, object]:
    return {
        "rank_evidence_status": "fresh",
        "rank_ordinal": rank,
        "lead_strategy": lead,
    }


def test_fixed_short_breakout_freeze_is_immutable_and_six_hours_forward() -> None:
    state = research.ProspectiveShortBreakoutRankState(frozen_at_ms=1000)
    assert state.started_at_ms == 1000 + 6 * 3_600_000
    assert state.payload()["research_only"] is True
    assert state.payload()["execution_authority"] is False
    assert research.ProspectiveShortBreakoutRankState.from_payload(
        state.payload()
    ) == state
    changed = state.payload()
    rule = changed["rule"]
    assert isinstance(rule, dict)
    rule["skip_if_fresh_opening_rank_above"] = 10
    with pytest.raises(
        research.ProspectiveShortBreakoutRankError, match="drift"
    ):
        research.ProspectiveShortBreakoutRankState.from_payload(changed)
    with pytest.raises(ValueError, match="time"):
        research.ProspectiveShortBreakoutRankState(frozen_at_ms=True)


def test_all_forward_original_losses_are_retained_even_if_entry_context_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = research.ProspectiveShortBreakoutRankState(frozen_at_ms=1000)
    start = state.started_at_ms
    trades = (
        _trade("old", opened=start - 1, pnl="-100"),
        _trade("bad-rank", opened=start, pnl="-8"),
        _trade("winning-top3", opened=start + 1, pnl="9"),
        _trade("missing-fact", opened=start + 2, pnl="-12"),
        _trade("long-breakout", opened=start + 3, side=Direction.LONG, pnl="3"),
        _trade("non-breakout", opened=start + 4, pnl="-2"),
        _trade("lost-winner", opened=start + 5, pnl="4"),
    )
    contexts = {
        "bad-rank": _context(5),
        "winning-top3": _context(3),
        "missing-fact": None,
        "long-breakout": _context(9),
        "non-breakout": _context(15, lead="mean_reversion"),
        "lost-winner": _context(11),
    }

    def resolve(
        trade: SimpleNamespace,
        facts: object,
        features: object,
        ranks: object,
    ) -> tuple[dict[str, object] | None, str | None]:
        context = contexts[trade.trade_id]
        return context, None if context is not None else "missing decision"

    monkeypatch.setattr(research, "try_resolve_entry_context_row", resolve)
    report = research.prospective_short_breakout_rank_comparison(
        trades, None, None, None, state  # type: ignore[arg-type]
    )
    assert report["original_forward_closed_trades"] == 6
    assert report["scored_forward_closed_trades"] == 6
    assert report["unverified_original_entry_context_by_reason"] == {
        "missing decision": 1
    }
    overall = report["overall"]
    assert isinstance(overall, dict)
    assert overall["original_net_pnl"] == "-6"
    assert overall["candidate_skip_only_net_pnl"] == "-2"
    assert overall["candidate_minus_original_net_pnl"] == "4"
    assert overall["skipped"] == 2
    assert overall["skipped_original_winners"] == 1
    assert overall["skipped_original_losers"] == 1
    assert report["skipped_markets"] == {"BTC": 2}
    assert report["integrity_complete"] is False
    assert report["strict_descriptive_screen_passes"] is False
    assert report["full_account_trial"] is False
    assert report["ready_for_review"] is False
    assert report["execution_authority"] is False
    assert report["changes_strategy"] is False


def test_stale_rank_cannot_contribute_avoided_losses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = research.ProspectiveShortBreakoutRankState(frozen_at_ms=1)
    trade = _trade("stale", opened=state.started_at_ms, pnl="-20")
    monkeypatch.setattr(
        research, "try_resolve_entry_context_row",
        lambda *args: ({
            "rank_evidence_status": "stale",
            "rank_ordinal": None,
            "lead_strategy": "breakout",
        }, None),
    )
    report = research.prospective_short_breakout_rank_comparison(
        (trade,), None, None, None, state  # type: ignore[arg-type]
    )
    overall = report["overall"]
    assert isinstance(overall, dict)
    assert overall["original_net_pnl"] == "-20"
    assert overall["candidate_skip_only_net_pnl"] == "-20"
    assert overall["skipped"] == 0
    assert report["unverified_original_entry_context_by_reason"] == {"stale": 1}


def test_duplicate_ids_and_invalid_verified_rank_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = research.ProspectiveShortBreakoutRankState(frozen_at_ms=0)
    trade = _trade("t", opened=state.started_at_ms)
    with pytest.raises(research.ProspectiveShortBreakoutRankError, match="duplicate"):
        research.prospective_short_breakout_rank_comparison(
            (trade, trade), None, None, None, state  # type: ignore[arg-type]
        )
    monkeypatch.setattr(
        research, "try_resolve_entry_context_row",
        lambda *args: ({
            "rank_evidence_status": "fresh",
            "rank_ordinal": True,
            "lead_strategy": "breakout",
        }, None),
    )
    with pytest.raises(
        research.ProspectiveShortBreakoutRankError, match="ordinal"
    ):
        research.prospective_short_breakout_rank_comparison(
            (trade,), None, None, None, state  # type: ignore[arg-type]
        )


def test_sum_only_frozen_cashflows_without_rounding_away_net_edge() -> None:
    rows = [
        (_trade("one", opened=1, pnl="10000"), False),
        (_trade("two", opened=2, pnl="0.000000000000000000000001"), False),
        (_trade("three", opened=3, pnl="-10000"), False),
    ]
    economics = research._economics(rows)
    assert economics["original_net_pnl"] == "1E-24"
    assert economics["candidate_skip_only_net_pnl"] == "1E-24"
    assert economics["candidate_absolute_positive"] is True
