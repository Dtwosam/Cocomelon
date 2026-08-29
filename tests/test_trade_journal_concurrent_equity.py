from dataclasses import replace
from decimal import Decimal

from cocomelon.journal.assembler import JournalInconsistency, assemble_trade_journal_entry
from tests.test_trade_journal_assembler import lifecycle


def test_trade_journal_allows_unrelated_concurrent_account_equity_drift() -> None:
    item = lifecycle()
    unrelated_open_position_equity_move = Decimal("3.155688")

    result = assemble_trade_journal_entry(
        replace(
            item,
            equity_after=item.equity_after + unrelated_open_position_equity_move,
        )
    )

    assert not isinstance(result, JournalInconsistency)
    assert result.net_pnl == Decimal("18.991")
    assert result.equity_before == item.equity_before
    assert result.equity_after == item.equity_after + unrelated_open_position_equity_move
