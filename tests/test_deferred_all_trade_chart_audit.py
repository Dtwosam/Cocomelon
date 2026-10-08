from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.deferred_all_trade_chart_audit import (
    AllPaperTradeChartAuditError,
    _compact_marks,
    _path_gap_ms,
    all_paper_trade_chart_audit,
    render_trade_charts,
)


class EmptyFacts:
    def load_decision_by_strategy_id(
        self, decision_id: str, run_id: str
    ) -> None:
        return None


def _trade(n: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=f"t{n}",
        market=MarketId("", "SOL"),
        direction=Direction.LONG,
        opened_at_ms=1000 * n,
        closed_at_ms=1000 * n + 100,
        entry_price=Decimal("10"),
        exit_price=Decimal("9"),
        initial_stop=Decimal("9.5"),
        filled_quantity=Decimal("2"),
        replay_run_id="continuous-paper-mainnet-v1",
        strategy_decision_id="decision",
        feature_snapshot_id="feature",
        gross_realized_pnl=Decimal("-2"),
        entry_fees=Decimal("0.2"),
        exit_fees=Decimal("0.3"),
        funding_cash_pnl=Decimal("0.1"),
        entry_slippage_amount=Decimal("0.1"),
        exit_slippage_amount=Decimal("0.1"),
        net_pnl=Decimal("-2.4"),
        net_r=Decimal("-1.2"),
        mfe=None,
        mae=None,
        exit_reason="MARK_STOP_TRIGGERED",
        holding_duration_ms=100,
    )


def _path(n: int = 1) -> dict[str, object]:
    return {
        "trade_id": f"t{n}",
        "market": "SOL",
        "direction": "long",
        "opened_at_ms": n * 1000,
        "closed_at_ms": n * 1000 + 100,
        "entry_price": "10",
        "exit_price": "9",
        "path_complete": True,
        "marks": [
            {"available_at_ms": n * 1000 + j, "mark_px": str(Decimal("10") - Decimal(j) / 100)}
            for j in range(0, 100, 10)
        ],
        "known_gap_intervals": [],
    }


def test_all_paper_trades_included_even_when_chart_missing() -> None:
    one = _trade(1)
    two = _trade(2)
    report = all_paper_trade_chart_audit((one, two), EmptyFacts(), (_path(1),))
    assert report["total_journal_trades"] == 2
    assert report["trades_included_in_economics"] == 2
    assert report["economics"]["overall"]["net_pnl"] == "-4.8"
    assert report["complete_chart_paths"] == 1
    assert report["missing_chart_path_trade_ids"] == ["t2"]
    assert report["trades"][1]["chart_coverage_complete"] is False
    assert report["execution_authority"] is False
    page = render_trade_charts(report)
    assert "MARK_STOP_TRIGGERED" in page
    assert "No recorded chart path" in page


def test_trade_chart_binds_actual_trade_identity_and_exit() -> None:
    bad = _path()
    bad["exit_price"] = "11"
    with pytest.raises(AllPaperTradeChartAuditError, match="entry-exit mismatch"):
        all_paper_trade_chart_audit((_trade(),), EmptyFacts(), (bad,))


def test_trades_not_in_journal_are_never_quietly_charted() -> None:
    with pytest.raises(AllPaperTradeChartAuditError, match="without a journal"):
        all_paper_trade_chart_audit((_trade(),), EmptyFacts(), (_path(1), _path(2)))


def test_known_gaps_exclude_unclean_trade_charts() -> None:
    gap = _path()
    gap["known_gap_intervals"] = [[1010, 1070]]
    report = all_paper_trade_chart_audit((_trade(),), EmptyFacts(), (gap,))
    assert report["complete_chart_paths"] == 0
    assert report["path_gap_affected_trades"] == 1
    assert report["trades"][0]["chart_known_gap_duration_ms"] == 60


def test_open_gap_never_counts_as_clean() -> None:
    assert _path_gap_ms({"known_gap_intervals": [[995, None]]}, 1000, 1100) is None


def test_chart_compaction_preserves_intrabar_reversal() -> None:
    marks = [
        {"available_at_ms": i, "mark_px": str(
            Decimal("100") + (Decimal("35") if i == 53 else Decimal("-20") if i == 54 else Decimal(i) / 100)
        )}
        for i in range(800)
    ]
    result = _compact_marks(marks)
    assert len(result) <= 144
    assert [53, "135"] in result
    assert [54, "80"] in result
    assert result[0][0] == 0
    assert result[-1][0] == 799
