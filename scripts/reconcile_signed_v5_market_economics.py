"""Reconcile signed independent v5 paper accounts by market, not by skipped trades.

Research-only, exact-checkpoint diagnostic. Does NOT estimate causal avoided losses,
trade replacement benefits, or post-anchor experiment readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from cocomelon.research.loss_context_paired_shadow_review import verify_review_ledger

SCOPED_V5_ROOT = "loss-context-paired-portfolio-shadow-scoped-v5"
ZERO = Decimal("0")


class PairedMarketEconomicsError(RuntimeError):
    """Never publish a market split that fails the signed account identity."""


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _object(raw: object, field: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise PairedMarketEconomicsError(f"{field} must be an object")
    return raw


def _decimal(raw: object, field: str) -> Decimal:
    if not isinstance(raw, str):
        raise PairedMarketEconomicsError(f"{field} is not a decimal string")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise PairedMarketEconomicsError(f"{field} is not decimal") from exc
    if not value.is_finite():
        raise PairedMarketEconomicsError(f"{field} is nonfinite")
    return value


def _market(raw: object) -> str:
    if not isinstance(raw, str) or not raw or raw.strip() != raw:
        raise PairedMarketEconomicsError("invalid market identifier")
    return raw


def _records(db: sqlite3.Connection, table: str) -> list[dict[str, object]]:
    return [
        _object(json.loads(row[0]), table)
        for row in db.execute(f"SELECT payload_json FROM {table}")
    ]


def _lane(root: Path, lane: str, expected_id: str,
          signed: dict[str, object]) -> dict[str, object]:
    path = root / f"{lane}-execution.sqlite3"
    if not path.is_file():
        raise PairedMarketEconomicsError(f"{lane} account database missing")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        state_rows = db.execute(
            "SELECT state_id, payload_json FROM paper_account_state"
        ).fetchall()
        if len(state_rows) != 1 or state_rows[0][0] != expected_id:
            raise PairedMarketEconomicsError(f"{lane} signed state ID mismatch")
        account = _object(json.loads(state_rows[0][1]), f"{lane} account")
        # A market's marked equity contribution is signed cash flows from
        # real fills + remaining signed inventory at its *stored* latest mark,
        # minus its *actual* fill fees plus its stored funding cash deltas.
        components: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: {k: ZERO for k in
                     ("cashflow", "signed_quantity", "mark_value", "fees", "funding")}
        )
        for fill in _records(db, "paper_fills"):
            market = _market(fill.get("market"))
            side = fill.get("side")
            if side not in ("buy", "sell"):
                raise PairedMarketEconomicsError("invalid fill side")
            qty = _decimal(fill.get("quantity"), "fill quantity")
            notional = _decimal(fill.get("notional"), "fill notional")
            fee = _decimal(fill.get("taker_fee"), "fill fee")
            if qty <= ZERO or notional <= ZERO or fee < ZERO:
                raise PairedMarketEconomicsError("invalid fill economics")
            sign = Decimal("1") if side == "buy" else Decimal("-1")
            components[market]["signed_quantity"] += sign * qty
            components[market]["cashflow"] -= sign * notional
            components[market]["fees"] += fee
        for position in _records(db, "paper_positions"):
            market = _market(position.get("market"))
            side = position.get("side")
            if side not in ("long", "short"):
                raise PairedMarketEconomicsError("invalid position side")
            qty = _decimal(position.get("quantity"), "position quantity")
            mark = _decimal(position.get("latest_mark"), "last observed mark")
            if qty <= ZERO or mark <= ZERO:
                raise PairedMarketEconomicsError("invalid open position")
            sign = Decimal("1") if side == "long" else Decimal("-1")
            components[market]["mark_value"] += sign * qty * mark
            components[market]["signed_quantity"] -= sign * qty
        for accrual in _records(db, "paper_funding_events"):
            market = _market(accrual.get("market"))
            components[market]["funding"] += _decimal(
                accrual.get("cash_delta"), "funding cash delta"
            )
        if any(c["signed_quantity"] != ZERO for c in components.values()):
            raise PairedMarketEconomicsError(
                f"{lane} fills and open position quantities disagree"
            )
        total_fees = sum((c["fees"] for c in components.values()), ZERO)
        total_funding = sum((c["funding"] for c in components.values()), ZERO)
        if total_fees != _decimal(account.get("cumulative_fees"), "account fees"):
            raise PairedMarketEconomicsError(f"{lane} fees do not reconcile")
        if total_funding != _decimal(
            account.get("cumulative_funding"), "account funding"
        ):
            raise PairedMarketEconomicsError(f"{lane} funding does not reconcile")
        by_market = {
            market: c["cashflow"] + c["mark_value"] - c["fees"] + c["funding"]
            for market, c in components.items()
        }
        net = sum(by_market.values(), ZERO)
        equity = _decimal(account.get("equity"), "account equity")
        initial = _decimal(account.get("starting_cash"), "starting cash")
        expected_net = _decimal(signed.get("total_account_pnl"), f"{lane} signed PnL")
        if net != expected_net or equity - initial != net:
            raise PairedMarketEconomicsError(
                f"{lane} per-market PnL does not equal signed account PnL"
            )
        return {
            "account_state_id": expected_id,
            "signed_total_account_pnl": str(net),
            "signed_equity": str(equity),
            "fill_fees": str(total_fees),
            "funding": str(total_funding),
            "markets": {k: str(v) for k, v in sorted(by_market.items())},
            # Exact additive whole-account mark/cash anatomy from the SAME
            # authenticated SQLite records. These are NOT realized-vs-
            # unrealized PnL: closing a position shifts value from open
            # inventory marks into signed fill cash flows.
            "market_components": {
                market: {
                    "filled_cashflow": str(c["cashflow"]),
                    "open_inventory_mark_value": str(c["mark_value"]),
                    "fill_fees": str(c["fees"]),
                    "funding_cash": str(c["funding"]),
                }
                for market, c in sorted(components.items())
            },
        }
    finally:
        db.close()


def reconcile(root: Path) -> dict[str, object]:
    scoped = root / SCOPED_V5_ROOT
    state = _object(
        json.loads((scoped / "paired-shadow-state.json").read_text(
            encoding="utf-8"
        )), "signed state"
    )
    unsigned = dict(state)
    recorded_digest = unsigned.pop("state_digest", None)
    if (
        not isinstance(recorded_digest, str)
        or recorded_digest != _digest(unsigned)
        or state.get("schema_version") != 2
        or state.get("research_only") is not True
        or state.get("shadow_only") is not True
        or state.get("handoff_safe") is not True
        or state.get("historical_gap_scope_tainted") is not False
        or state.get("execution_authority") is not False
        or state.get("promotion_authority") is not False
    ):
        raise PairedMarketEconomicsError("unsafe/unsigned v5 shadow checkpoint")
    candidate_id = state.get("portfolio_shadow_candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise PairedMarketEconomicsError("frozen candidate missing")
    rows = verify_review_ledger(
        scoped / "review-ledger.jsonl", candidate_id=candidate_id,
    )
    if (
        not rows
        or len(rows) != state.get("review_ledger_row_count")
        or rows[-1].get("row_digest") != state.get("review_ledger_latest_row_digest")
        or rows[-1].get("record_count") != state.get("record_count")
    ):
        raise PairedMarketEconomicsError("signed review checkpoint lineage mismatch")
    last = rows[-1]
    with localcontext() as ctx:
        ctx.prec = 70
        lanes = {}
        for lane in ("baseline", "candidate"):
            info = _object(state.get(lane), f"signed {lane}")
            account_id = info.get("account_state_id")
            if not isinstance(account_id, str) or not account_id:
                raise PairedMarketEconomicsError(f"{lane} account ID absent")
            lanes[lane] = _lane(
                scoped, lane, account_id,
                _object(last.get(lane), f"signed {lane} review"),
            )
        baseline = lanes["baseline"]["markets"]
        candidate = lanes["candidate"]["markets"]
        markets = {}
        for market in sorted(set(baseline) | set(candidate)):
            b = Decimal(baseline.get(market, "0"))
            c = Decimal(candidate.get(market, "0"))
            markets[market] = {
                "baseline_account_pnl": str(b),
                "candidate_account_pnl": str(c),
                "candidate_minus_baseline": str(c - b),
            }
        delta = (
            Decimal(lanes["candidate"]["signed_total_account_pnl"])
            - Decimal(lanes["baseline"]["signed_total_account_pnl"])
        )
        if (
            sum((Decimal(x["candidate_minus_baseline"]) for x in
                 markets.values()), ZERO) != delta
            or delta != _decimal(
                last.get("candidate_minus_baseline_total_account_pnl"),
                "signed comparison delta",
            )
        ):
            raise PairedMarketEconomicsError("signed cross-lane delta mismatch")
    return {
        "schema_version": 1,
        "kind": "signed-v5-paired-market-accounting-reconciliation",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "economic_scope": "cumulative_through_last_signed_checkpoint_not_forward_verdict",
        "causal_block_credit": False,
        "source_state_digest": recorded_digest,
        "source_latest_review_row_digest": last["row_digest"],
        "source_record_count": state["record_count"],
        "source_candidate_id": candidate_id,
        "baseline": lanes["baseline"],
        "candidate": lanes["candidate"],
        "candidate_minus_baseline_total_account_pnl": str(delta),
        "by_market": markets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    report = reconcile(args.state_root)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "state_digest": report["source_state_digest"],
        "candidate_minus_baseline_total_account_pnl": report[
            "candidate_minus_baseline_total_account_pnl"
        ],
        "market_count": len(report["by_market"]),
        "authority": "RESEARCH ONLY / NO EXECUTION",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
