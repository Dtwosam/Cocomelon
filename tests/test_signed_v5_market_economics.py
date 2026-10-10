"""Account-derived, signed v5 market attribution must never invent profits."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import reconcile_signed_v5_market_economics as economics


def _write_lane(
    root: Path,
    lane: str,
    *,
    market: str,
    side: str,
    mark: str,
    fee: str,
    funding: str,
    net: str,
) -> None:
    db = sqlite3.connect(
        root / f"{lane}-execution.sqlite3"
    )
    db.executescript(
        """
        CREATE TABLE paper_account_state(state_id TEXT, payload_json TEXT);
        CREATE TABLE paper_fills(payload_json TEXT);
        CREATE TABLE paper_positions(payload_json TEXT);
        CREATE TABLE paper_funding_events(payload_json TEXT);
        """
    )
    db.execute(
        "INSERT INTO paper_account_state VALUES (?, ?)",
        (
            f"{lane}-state",
            json.dumps({
                "starting_cash": "10000",
                "equity": str(10000 + int(net)),
                "cumulative_fees": fee,
                "cumulative_funding": funding,
            }),
        ),
    )
    db.execute(
        "INSERT INTO paper_fills VALUES (?)",
        (json.dumps({
            "market": market,
            "side": side,
            "quantity": "1",
            "notional": "100",
            "taker_fee": fee,
        }),),
    )
    db.execute(
        "INSERT INTO paper_positions VALUES (?)",
        (json.dumps({
            "market": market,
            "side": "long" if side == "buy" else "short",
            "quantity": "1",
            "latest_mark": mark,
        }),),
    )
    if funding != "0":
        db.execute(
            "INSERT INTO paper_funding_events VALUES (?)",
            (json.dumps({"market": market, "cash_delta": funding}),),
        )
    db.commit()
    db.close()


def _fixture(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scoped = root / economics.SCOPED_V5_ROOT
    scoped.mkdir(parents=True)
    _write_lane(
        scoped, "baseline", market="ALPHA", side="buy",
        mark="110", fee="1", funding="2", net="11",
    )
    _write_lane(
        scoped, "candidate", market="BETA", side="sell",
        mark="110", fee="1", funding="0", net="-11",
    )
    state: dict[str, object] = {
        "schema_version": 2,
        "research_only": True,
        "shadow_only": True,
        "handoff_safe": True,
        "historical_gap_scope_tainted": False,
        "execution_authority": False,
        "promotion_authority": False,
        "portfolio_shadow_candidate_id": "frozen-candidate",
        "record_count": 123,
        "review_ledger_row_count": 1,
        "review_ledger_latest_row_digest": "row-digest",
        "baseline": {"account_state_id": "baseline-state"},
        "candidate": {"account_state_id": "candidate-state"},
    }
    state["state_digest"] = economics._digest(state)
    (scoped / "paired-shadow-state.json").write_text(
        json.dumps(state), encoding="utf-8",
    )
    (scoped / "review-ledger.jsonl").write_text("checked-by-mock\n", encoding="utf-8")
    row = {
        "row_digest": "row-digest",
        "record_count": 123,
        "baseline": {"total_account_pnl": "11"},
        "candidate": {"total_account_pnl": "-11"},
        "candidate_minus_baseline_total_account_pnl": "-22",
    }
    monkeypatch.setattr(
        economics, "verify_review_ledger",
        lambda path, *, candidate_id: (row,),
    )
    return scoped


def test_per_market_actual_cashflows_reconcile_both_signed_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture(tmp_path, monkeypatch)
    report = economics.reconcile(tmp_path)
    assert report["research_only"] is True
    assert report["promotion_authority"] is False
    assert report["execution_authority"] is False
    assert report["causal_block_credit"] is False
    assert report["economic_scope"].startswith("cumulative_through")
    assert report["baseline"]["signed_total_account_pnl"] == "11"
    assert report["baseline"]["fill_fees"] == "1"
    assert report["baseline"]["funding"] == "2"
    assert report["candidate"]["signed_total_account_pnl"] == "-11"
    assert report["candidate_minus_baseline_total_account_pnl"] == "-22"
    assert report["baseline"]["market_components"]["ALPHA"] == {
        "filled_cashflow": "-100",
        "open_inventory_mark_value": "110",
        "fill_fees": "1",
        "funding_cash": "2",
    }
    assert report["candidate"]["market_components"]["BETA"] == {
        "filled_cashflow": "100",
        "open_inventory_mark_value": "-110",
        "fill_fees": "1",
        "funding_cash": "0",
    }
    assert report["by_market"]["ALPHA"] == {
        "baseline_account_pnl": "11",
        "candidate_account_pnl": "0",
        "candidate_minus_baseline": "-11",
    }
    assert report["by_market"]["BETA"] == {
        "baseline_account_pnl": "0",
        "candidate_account_pnl": "-11",
        "candidate_minus_baseline": "-11",
    }


@pytest.mark.parametrize(
    ("table", "lane", "target", "replacement", "reason"),
    [
        (
            "paper_account_state", "baseline",
            "baseline-state", "forged-state",
            "signed state ID mismatch",
        ),
        (
            "paper_fills", "candidate",
            '"taker_fee": "1"', '"taker_fee": "2"',
            "fees do not reconcile",
        ),
        (
            "paper_positions", "candidate",
            '"latest_mark": "110"', '"latest_mark": "111"',
            "per-market PnL does not equal signed account PnL",
        ),
        (
            "paper_positions", "candidate",
            '"quantity": "1"', '"quantity": "2"',
            "fills and open position quantities disagree",
        ),
    ],
)
def test_refuse_unreconciled_account_or_forced_economic_advantage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    table: str, lane: str, target: str, replacement: str, reason: str,
) -> None:
    scoped = _fixture(tmp_path, monkeypatch)
    db = sqlite3.connect(scoped / f"{lane}-execution.sqlite3")
    field = "state_id" if table == "paper_account_state" else "payload_json"
    value = db.execute(f"SELECT {field} FROM {table} LIMIT 1").fetchone()[0]
    assert target in value
    db.execute(
        f"UPDATE {table} SET {field} = ?",
        (value.replace(target, replacement),),
    )
    db.commit()
    db.close()
    with pytest.raises(economics.PairedMarketEconomicsError, match=reason):
        economics.reconcile(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_authority", True),
        ("promotion_authority", True),
        ("historical_gap_scope_tainted", True),
        ("handoff_safe", False),
    ],
)
def test_reject_unsafe_signed_research_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    field: str, value: object,
) -> None:
    scoped = _fixture(tmp_path, monkeypatch)
    p = scoped / "paired-shadow-state.json"
    state = json.loads(p.read_text(encoding="utf-8"))
    state[field] = value
    state.pop("state_digest")
    state["state_digest"] = economics._digest(state)
    p.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(economics.PairedMarketEconomicsError, match="unsafe"):
        economics.reconcile(tmp_path)


def test_tampered_state_digest_fails_before_reading_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoped = _fixture(tmp_path, monkeypatch)
    p = scoped / "paired-shadow-state.json"
    state = json.loads(p.read_text(encoding="utf-8"))
    state["state_digest"] = "0" * 64
    p.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(economics.PairedMarketEconomicsError, match="unsigned"):
        economics.reconcile(tmp_path)


def test_does_not_confuse_absent_post_anchor_sample_with_cumulative_tie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture(tmp_path, monkeypatch)
    report = economics.reconcile(tmp_path)
    assert report["economic_scope"] == (
        "cumulative_through_last_signed_checkpoint_not_forward_verdict"
    )
    assert report["candidate_minus_baseline_total_account_pnl"] == "-22"
    assert "ready_for_review" not in report
    assert "hypothetical_saved_pnl" not in report


def test_upload_step_is_after_paired_signed_state_and_fails_closed() -> None:
    yml = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8",
    )
    signer = yml.index("- name: Upload paired loss-context portfolio shadow state")
    proof = yml.index("- name: Reconcile signed v5 paired market economics")
    uploader = yml.index("- name: Upload signed v5 market economics attribution")
    assert signer < proof < uploader
    assert "scripts/reconcile_signed_v5_market_economics.py" in yml[proof:uploader]
    assert "continue-on-error: true" in yml[signer:proof]
    assert "continuous-paper-v5-market-economics-" in yml[uploader:]
    assert "live_orders: true" not in yml[proof:uploader]
