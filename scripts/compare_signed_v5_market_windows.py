"""Compare authenticated independent v5 account market reports over an actual window.

A diagnostic of cumulative after-cost account equity differences, including
marked open inventory. This does not score the frozen candidate, establish
causality, authenticate the raw review-ledger chain, or authorize trades.
Inputs must be the exact compact outputs of reconcile_signed_v5_market_economics.
"""
from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

ZERO = Decimal("0")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
KIND = "signed-v5-paired-market-accounting-reconciliation"
SCOPE = "cumulative_through_last_signed_checkpoint_not_forward_verdict"


class V5WindowComparisonError(ValueError):
    """Refuse invalid or unmatched accounting evidence."""


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) for k in value
    ):
        raise V5WindowComparisonError(f"{field}: expected object")
    return value


def _number(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise V5WindowComparisonError(f"{field}: expected decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise V5WindowComparisonError(f"{field}: invalid decimal") from exc
    if not number.is_finite():
        raise V5WindowComparisonError(f"{field}: nonfinite decimal")
    return number


def _name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise V5WindowComparisonError(f"{field}: invalid identifier")
    return value


def _lane(obj: dict[str, object], label: str) -> dict[str, object]:
    raw = _object(obj.get(label), label)
    _name(raw.get("account_state_id"), f"{label} state ID")
    pnl = _number(raw.get("signed_total_account_pnl"), f"{label} PnL")
    equity = _number(raw.get("signed_equity"), f"{label} equity")
    fees = _number(raw.get("fill_fees"), f"{label} fees")
    funding = _number(raw.get("funding"), f"{label} funding")
    if fees < ZERO or equity <= ZERO:
        raise V5WindowComparisonError(f"{label}: invalid fees or equity")
    amounts = {
        _name(m, "market"): _number(v, f"{label}.{m}")
        for m, v in _object(raw.get("markets"), f"{label} markets").items()
    }
    if sum(amounts.values(), ZERO) != pnl:
        raise V5WindowComparisonError(f"{label}: market PnL does not reconcile")
    return {
        "equity": equity,
        "pnl": pnl,
        "fees": fees,
        "funding": funding,
        "markets": amounts,
        "starting_cash": equity - pnl,
    }


def _validate(report: object, label: str) -> dict[str, object]:
    obj = _object(report, label)
    for key, expected in (
        ("schema_version", 1),
        ("kind", KIND),
        ("economic_scope", SCOPE),
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("causal_block_credit", False),
    ):
        if type(obj.get(key)) is not type(expected) or obj[key] != expected:
            raise V5WindowComparisonError(f"{label}: invalid {key}")
    _name(obj.get("source_candidate_id"), f"{label} candidate")
    for key in ("source_state_digest", "source_latest_review_row_digest"):
        value = obj.get(key)
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            raise V5WindowComparisonError(f"{label}: invalid {key}")
    count = obj.get("source_record_count")
    if type(count) is not int or count < 0:
        raise V5WindowComparisonError(f"{label}: invalid record count")
    base = _lane(obj, "baseline")
    candidate = _lane(obj, "candidate")
    if base["starting_cash"] != candidate["starting_cash"]:
        raise V5WindowComparisonError(f"{label}: unequal starting cash")
    delta = _number(obj.get("candidate_minus_baseline_total_account_pnl"),
                    f"{label} signed delta")
    if candidate["pnl"] - base["pnl"] != delta:
        raise V5WindowComparisonError(f"{label}: signed PnL delta mismatch")
    keys = set(base["markets"]) | set(candidate["markets"])
    reported = _object(obj.get("by_market"), f"{label} markets delta")
    if keys != set(reported):
        raise V5WindowComparisonError(f"{label}: market universe mismatch")
    for market in keys:
        actual = _object(reported[market], market)
        if set(actual) != {
            "baseline_account_pnl", "candidate_account_pnl",
            "candidate_minus_baseline",
        }:
            raise V5WindowComparisonError(f"{label}: {market} missing fields")
        base_amt = base["markets"].get(market, ZERO)
        candidate_amt = candidate["markets"].get(market, ZERO)
        if (
            _number(actual["baseline_account_pnl"], "baseline market") != base_amt
            or _number(actual["candidate_account_pnl"], "candidate market")
            != candidate_amt
            or _number(actual["candidate_minus_baseline"], "market delta")
            != candidate_amt - base_amt
        ):
            raise V5WindowComparisonError(f"{label}: {market} does not reconcile")
    return {"source": obj, "baseline": base,
            "candidate": candidate, "delta": delta}


def compare(before: object, after: object) -> dict[str, object]:
    """Inspect actual new marked-account economics, never saved-loss guesses."""
    with localcontext() as ctx:
        ctx.prec = 96
        prior = _validate(before, "before")
        later = _validate(after, "after")
        a, b = prior["source"], later["source"]
        if a["source_candidate_id"] != b["source_candidate_id"]:
            raise V5WindowComparisonError("frozen candidate changed")
        if b["source_record_count"] <= a["source_record_count"]:
            raise V5WindowComparisonError("checkpoints out of order")
        if a["source_state_digest"] == b["source_state_digest"]:
            raise V5WindowComparisonError("repeated source state")
        if (a["source_latest_review_row_digest"]
                == b["source_latest_review_row_digest"]):
            raise V5WindowComparisonError("repeated review row")
        markets = sorted(set(prior["baseline"]["markets"])
                         | set(prior["candidate"]["markets"])
                         | set(later["baseline"]["markets"])
                         | set(later["candidate"]["markets"]))
        rows: dict[str, dict[str, str]] = {}
        for market in markets:
            original = (
                later["baseline"]["markets"].get(market, ZERO)
                - prior["baseline"]["markets"].get(market, ZERO)
            )
            challenger = (
                later["candidate"]["markets"].get(market, ZERO)
                - prior["candidate"]["markets"].get(market, ZERO)
            )
            rows[market] = {
                "baseline_window_pnl": str(original),
                "candidate_window_pnl": str(challenger),
                "candidate_minus_baseline_window_pnl": str(
                    challenger - original
                ),
            }
        lanes = {}
        for name in ("baseline", "candidate"):
            first, last = prior[name], later[name]
            if first["starting_cash"] != last["starting_cash"]:
                raise V5WindowComparisonError(f"{name}: starting capital changed")
            paid = last["fees"] - first["fees"]
            if paid < ZERO:
                raise V5WindowComparisonError(f"{name}: fees decreased")
            pnl = last["pnl"] - first["pnl"]
            if sum((Decimal(v[f"{name}_window_pnl"]) for v in
                    rows.values()), ZERO) != pnl:
                raise V5WindowComparisonError(f"{name}: window PnL mismatch")
            lanes[name] = {
                "marked_account_pnl_change": str(pnl),
                "paid_fees_in_window": str(paid),
                "funding_cash_delta_in_window": str(
                    last["funding"] - first["funding"]
                ),
                "closing_marked_equity": str(last["equity"]),
            }
        advantage = (
            Decimal(lanes["candidate"]["marked_account_pnl_change"])
            - Decimal(lanes["baseline"]["marked_account_pnl_change"])
        )
        if (
            later["delta"] - prior["delta"] != advantage
            or sum((Decimal(v["candidate_minus_baseline_window_pnl"])
                    for v in rows.values()), ZERO) != advantage
        ):
            raise V5WindowComparisonError("window PnL does not reconcile")
        return {
            "schema_version": 1,
            "kind": "signed-v5-descriptive-incremental-market-window",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "causal_block_credit": False,
            "verified_review_ledger_contiguity": False,
            "not_frozen_anchor_review": True,
            "economic_scope": "between_two_cumulative_signed_account_snapshots",
            "note": (
                "Includes inventory marks as well as actual fees and cash "
                "flows; not realized-only PnL or causal avoided-loss credit."
            ),
            "source_candidate_id": a["source_candidate_id"],
            "before_state_digest": a["source_state_digest"],
            "after_state_digest": b["source_state_digest"],
            "before_review_row_digest": a["source_latest_review_row_digest"],
            "after_review_row_digest": b["source_latest_review_row_digest"],
            "before_record_count": a["source_record_count"],
            "after_record_count": b["source_record_count"],
            "baseline": lanes["baseline"],
            "candidate": lanes["candidate"],
            "candidate_minus_baseline_window_pnl": str(advantage),
            "candidate_minus_baseline_cumulative_pnl_at_end": str(later["delta"]),
            "by_market": rows,
            "largest_candidate_disadvantages": [
                market for market in sorted(
                    markets,
                    key=lambda market: (
                        Decimal(rows[market][
                            "candidate_minus_baseline_window_pnl"
                        ]),
                        market,
                    ),
                )
                if Decimal(rows[market][
                    "candidate_minus_baseline_window_pnl"
                ]) < ZERO
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before_report", type=Path)
    parser.add_argument("after_report", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    result = compare(
        json.loads(args.before_report.read_text(encoding="utf-8")),
        json.loads(args.after_report.read_text(encoding="utf-8")),
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "candidate_minus_baseline_window_pnl":
            result["candidate_minus_baseline_window_pnl"],
        "candidate_minus_baseline_cumulative_pnl_at_end":
            result["candidate_minus_baseline_cumulative_pnl_at_end"],
        "authority": "RESEARCH ONLY / NO EXECUTION",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
