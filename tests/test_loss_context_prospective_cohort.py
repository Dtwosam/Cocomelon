from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research import loss_context_prospective_cohort as cohort


@dataclass(frozen=True)
class _ClosedTrade:
    trade_id: str
    opened_at_ms: int
    closed_at_ms: int
    net_pnl: Decimal
    market: MarketId
    direction: Direction


def _trade(
    ident: str,
    *,
    opened: int,
    closed: int,
    pnl: str = "-2",
    market: str = "HYPE",
    side: Direction = Direction.SHORT,
) -> _ClosedTrade:
    return _ClosedTrade(
        ident, opened, closed, Decimal(pnl), MarketId("", market), side
    )


def _as_journal(*trades: _ClosedTrade) -> tuple[TradeJournalEntry, ...]:
    return cast(tuple[TradeJournalEntry, ...], trades)


def _anchor(
    tmp_path: Path, trades: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    anchor, created = cohort.ensure_anchor(
        tmp_path,
        trades,
        frozen_at_ms=1_000_000,
        source_paper_run_id=1234,
        source_paper_run_attempt=1,
        source_paper_head_sha="a" * 40,
    )
    assert created is True
    return anchor


def _fake_audit(
    monkeypatch: pytest.MonkeyPatch, *, complete: bool = True,
) -> list[tuple[TradeJournalEntry, ...]]:
    seen: list[tuple[TradeJournalEntry, ...]] = []

    def audit(
        trades: tuple[TradeJournalEntry, ...],
        *_stores: object,
    ) -> dict[str, object]:
        seen.append(trades)
        return {
            "trade_count": len(trades),
            "baseline_normalization_complete": complete,
            "baseline_unresolved_trade_count": 0 if complete else 1,
            "baseline_unresolved_reason_counts": (
                {} if complete else {"missing feature snapshot": 1}
            ),
            "qualifying_loss_streak_count": 2,
            "context_filter_stability": {"stable_candidate_count": 0},
        }

    monkeypatch.setattr(cohort, "loss_streak_context_audit", audit)
    return seen


def test_freeze_reuses_original_cutover_and_historical_commitment(
    tmp_path: Path,
) -> None:
    before = _trade("old", opened=100, closed=200)
    original = _as_journal(before)
    anchor = _anchor(tmp_path, original)
    path = tmp_path / cohort.ANCHOR_FILENAME
    encoded = path.read_bytes()

    after = _trade("new", opened=1_100_000, closed=1_200_000)
    reused, created = cohort.ensure_anchor(
        tmp_path, _as_journal(before, after),
        frozen_at_ms=2_000_000,
        source_paper_run_id=9999,
        source_paper_run_attempt=2,
        source_paper_head_sha="b" * 40,
    )

    assert created is False
    assert reused == anchor
    assert reused["frozen_at_ms"] == 1_000_000
    assert path.read_bytes() == encoded
    assert reused["source_closed_trade_count"] == 1
    assert cohort.load_anchor(tmp_path, _as_journal(before, after)) == anchor


def test_historical_trade_rewrite_or_loss_cannot_pass_witness(
    tmp_path: Path,
) -> None:
    before = _trade("old", opened=100, closed=200)
    _anchor(tmp_path, _as_journal(before))

    with pytest.raises(
        cohort.LossContextForwardCohortError,
        match="witness changed",
    ):
        cohort.load_anchor(tmp_path, _as_journal(replace(before, net_pnl=Decimal("3"))))
    with pytest.raises(
        cohort.LossContextForwardCohortError,
        match="witness changed",
    ):
        cohort.load_anchor(tmp_path, _as_journal())


def test_tampered_or_authority_granting_anchor_rejected(
    tmp_path: Path,
) -> None:
    trades = _as_journal(_trade("old", opened=100, closed=200))
    anchor = _anchor(tmp_path, trades)
    path = tmp_path / cohort.ANCHOR_FILENAME
    for field, value in (
        ("frozen_at_ms", 2_000_000),
        ("execution_authority", True),
        ("forward_only", False),
        ("anchor_id", "b" * 64),
    ):
        corrupted = {**anchor, field: value}
        path.write_text(json.dumps(corrupted), encoding="utf-8")
        with pytest.raises(cohort.LossContextForwardCohortError):
            cohort.load_anchor(tmp_path, trades)


def test_report_excludes_carryover_and_legacy_and_keeps_both_sides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _trade("old", opened=100, closed=200)
    anchor = _anchor(tmp_path, _as_journal(old))
    carryover = _trade("carryover", opened=900_000, closed=1_200_000)
    after_long = _trade(
        "forward-long", opened=1_100_000, closed=1_250_000,
        pnl="5", market="BTC", side=Direction.LONG,
    )
    after_short = _trade(
        "forward-short", opened=1_200_000, closed=1_300_000,
        pnl="-2", market="ETH",
    )
    seen = _fake_audit(monkeypatch)
    report = cohort.build_forward_report(
        anchor, _as_journal(old, carryover, after_long, after_short),
        cast(object, None), cast(object, None), cast(object, None),
        observed_at_ms=1_400_000,
    )
    assert len(seen) == 1
    assert tuple(t.trade_id for t in seen[0]) == (
        "forward-long", "forward-short"
    )
    assert report["forward_closed_trades"] == 2
    assert report["carryover_excluded_closed_trades"] == 1
    assert report["forward_long_closed_trades"] == 1
    assert report["forward_short_closed_trades"] == 1
    assert report["forward_market_count"] == 2
    assert report["forward_net_closed_trade_pnl"] == "3"
    assert report["ready_for_research_discovery"] is False
    assert report["promotion_authority"] is False


def test_mature_cohort_requires_completeness_and_broad_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = _anchor(tmp_path, _as_journal())
    trades = _as_journal(
        *(
            _trade(
                f"forward-{i}",
                opened=1_200_000 + i * 120_000,
                closed=1_250_000 + i * 120_000,
                pnl="3" if i % 3 == 0 else "-1",
                market=("HYPE", "BTC", "ETH", "SOL")[i % 4],
                side=Direction.LONG if i % 2 else Direction.SHORT,
            )
            for i in range(30)
        )
    )
    seen = _fake_audit(monkeypatch)
    report = cohort.build_forward_report(
        anchor, trades, cast(object, None), cast(object, None),
        cast(object, None), observed_at_ms=1_000_000 + cohort.MIN_AGE_MS,
    )
    assert report["ready_for_research_discovery"] is True
    assert report["forward_non_loss_control_count"] == 10
    assert report["forward_market_count"] == 4
    assert report["strategy_promotion_eligible"] is False
    assert report["account_profitability_proven"] is False
    assert len(seen[0]) == 30

    _fake_audit(monkeypatch, complete=False)
    incomplete = cohort.build_forward_report(
        anchor, trades, cast(object, None), cast(object, None),
        cast(object, None), observed_at_ms=1_000_000 + cohort.MIN_AGE_MS,
    )
    assert incomplete["ready_for_research_discovery"] is False
    assert incomplete["forward_unresolved_trade_count"] == 1


def test_premature_or_backdated_source_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        cohort.LossContextForwardCohortError,
        match="already closed",
    ):
        cohort.make_anchor(
            _as_journal(_trade("future", opened=900_000, closed=1_000_001)),
            frozen_at_ms=1_000_000,
            source_paper_run_id=1234, source_paper_run_attempt=1,
            source_paper_head_sha="a" * 40,
        )
    anchor = _anchor(tmp_path, _as_journal())
    _fake_audit(monkeypatch)
    with pytest.raises(
        cohort.LossContextForwardCohortError,
        match="predates frozen",
    ):
        cohort.build_forward_report(
            anchor, _as_journal(), cast(object, None),
            cast(object, None), cast(object, None),
            observed_at_ms=999_999,
        )
