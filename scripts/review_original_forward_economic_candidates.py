"""Read-only economic veto across ORIGINAL completed PAPER research ZIP receipts.

Trust no filenames/paths or source-authentication claims from ZIPs. The
caller must independently bind EACH ZIP SHA256 to one original GitHub run,
attempt, artifact ID and completed upload job. This is a *negative* economic
triage tool, NEVER a profitability or trade-promotion certifier.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

MAX_ZIP_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 3 * 1024 * 1024
SOURCE_MEMBER = "all-paper-profitability-scoreboard.json"
SHORT_MEMBER = "prospective-short-breakout-rank-comparison.json"
COST_MEMBER = "prospective-entry-cost-r-comparison.json"
ZERO = Decimal("0")
CASH_ROUNDING = Decimal("1E-18")


class EconomicVetoError(ValueError):
    """Insufficient or contradictory unaltered original economic evidence."""


def _object(raw: object, name: str) -> dict[str, object]:
    if not isinstance(raw, dict) or any(not isinstance(k, str) for k in raw):
        raise EconomicVetoError(f"{name} is not an object")
    return cast(dict[str, object], raw)


def _amount(raw: object, name: str) -> Decimal:
    if not isinstance(raw, str):
        raise EconomicVetoError(f"{name} is not an exact decimal string")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise EconomicVetoError(f"{name} decimal invalid") from exc
    if not value.is_finite():
        raise EconomicVetoError(f"{name} nonfinite")
    return value


def _count(raw: object, name: str) -> int:
    if type(raw) is not int or raw < 0:
        raise EconomicVetoError(f"{name} must be nonnegative integer")
    return raw


def _zip_json(path: Path, *, expected_sha256: str, member: str) -> dict[str, object]:
    if (
        len(expected_sha256) != 64
        or any(c not in "0123456789abcdef" for c in expected_sha256)
        or not path.is_file()
        or path.stat().st_size > MAX_ZIP_BYTES
    ):
        raise EconomicVetoError("exact original ZIP identity invalid")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
            raise EconomicVetoError("GitHub original ZIP SHA256 mismatch")
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.namelist().count(member) != 1:
                raise EconomicVetoError("required original receipt not unique")
            item = archive.getinfo(member)
            if item.is_dir() or item.file_size > MAX_JSON_BYTES:
                raise EconomicVetoError("original receipt size invalid")
            with archive.open(item) as stream:
                data = stream.read(MAX_JSON_BYTES + 1)
            if len(data) != item.file_size or len(data) > MAX_JSON_BYTES:
                raise EconomicVetoError("original receipt expanded size invalid")
    except (zipfile.BadZipFile, OSError) as exc:
        raise EconomicVetoError("original GitHub ZIP unreadable") from exc
    try:
        parsed: object = json.loads(data)
    except (UnicodeError, ValueError) as exc:
        raise EconomicVetoError("original economic receipt JSON invalid") from exc
    return _object(parsed, "original economic receipt")


def _paper_overall(root: dict[str, object]) -> dict[str, object]:
    if (
        root.get("kind") != "entire-original-paper-profitability-attribution"
        or root.get("research_only") is not True
        or root.get("execution_authority") is not False
        or root.get("promotion_authority") is not False
        or root.get("ready_for_strategy_promotion") is not False
        or root.get("source_authentication")
        != "caller_must_verify_github_artifact_run_attempt_digest"
    ):
        raise EconomicVetoError("original paper study authority or identity invalid")
    data = _object(root.get("overall"), "whole closed journal")
    gross = _amount(data.get("gross_realized_pnl"), "gross")
    fees = _amount(data.get("fees"), "fees")
    funding = _amount(data.get("funding_cash_pnl"), "funding")
    net = _amount(data.get("net_pnl"), "net")
    net_r = _amount(data.get("net_r"), "net-R")
    closes = _count(data.get("trades"), "closes")
    if closes == 0 or fees < ZERO or abs((gross - fees + funding) - net) > CASH_ROUNDING:
        raise EconomicVetoError("whole booked gross/fees/funding/net do not reconcile")
    if _count(data.get("incomplete_chart_trades"), "missing charts") > closes:
        raise EconomicVetoError("incomplete original charts exceed booked closes")
    sides = root.get("side_cohorts")
    if not isinstance(sides, list) or len(sides) != 2:
        raise EconomicVetoError("whole booked sides missing")
    if sum(
        (_count(_object(row, "side cohort").get("trades"), "side closes")
         for row in sides)
    ) != closes or any(
        abs(sum(
            (_amount(_object(row, "side cohort").get(key), f"side {key}")
             for row in sides), ZERO,
        ) - recorded) > CASH_ROUNDING
        for key, recorded in (
            ("gross_realized_pnl", gross),
            ("fees", fees),
            ("funding_cash_pnl", funding),
            ("net_pnl", net),
            ("net_r", net_r),
        )
    ):
        raise EconomicVetoError("whole booked long/short cash or R mismatch")
    return {
        "closes": closes,
        "gross_usd": str(gross),
        "fees_usd": str(fees),
        "funding_usd": str(funding),
        "after_cost_closed_net_usd": str(net),
        "after_cost_net_r": str(net_r),
        "fee_drag_exceeds_gross": fees > gross,
        "original_charts_incomplete": _count(
            data["incomplete_chart_trades"], "missing charts",
        ),
        "full_signed_account_equity_verified": False,
        "original_exchange_events_verified": False,
    }


def _candidate(root: dict[str, object], *, expected: str,
               kind: str) -> dict[str, object]:
    if (
        root.get("candidate_id") != expected
        or root.get("enabled") is not True
        or root.get("error") is not None
        or root.get("ready_for_review") is not False
        or root.get("research_only") is not True
        or root.get("execution_authority") is not False
        or root.get("promotion_authority") is not False
    ):
        raise EconomicVetoError(f"{kind} research authority or identity invalid")
    overall = _object(root.get("overall"), f"{kind} forward economics")
    if kind == "short_breakout":
        source_n = _count(root.get("original_forward_closed_trades"), "short source")
        compared_n = _count(root.get("scored_forward_closed_trades"), "short compared")
        original_key = "original_net_pnl"
        candidate_key = "candidate_skip_only_net_pnl"
        delta_key = "candidate_minus_original_net_pnl"
        rkey = "candidate_minus_original_net_r"
        blocked = _count(overall.get("skipped"), "short skipped")
        originals = _amount(
            overall.get("skipped_original_net_pnl"), "short skipped actual net",
        )
        if source_n != compared_n or blocked > source_n:
            raise EconomicVetoError("short forward sample inconsistent")
    else:
        compared_n = source_n = _count(root.get("closed_prospective_trades"), "cost sample")
        original_key = "actual_net_pnl"
        candidate_key = "candidate_net_pnl"
        delta_key = "delta_net_pnl"
        rkey = "delta_net_r"
        blocked = _count(root.get("hypothetically_blocked_trades"), "cost blocked")
        if _count(root.get("retained_trades"), "cost retained") + blocked != source_n:
            raise EconomicVetoError("cost forward sample inconsistent")
    original = _amount(overall.get(original_key), f"{kind} actual net")
    candidate = _amount(overall.get(candidate_key), f"{kind} hypothetical net")
    delta = _amount(overall.get(delta_key), f"{kind} hypothetical delta")
    delta_r = _amount(overall.get(rkey), f"{kind} hypothetical delta R")
    if (
        compared_n == 0 or blocked > compared_n
        or abs(candidate - original - delta) > CASH_ROUNDING
        or (kind == "short_breakout" and abs(delta + originals) > CASH_ROUNDING)
    ):
        raise EconomicVetoError(f"{kind} booked hypothetical contribution invalid")
    strict = root.get("strict_descriptive_screen_passes")
    if type(strict) is not bool:
        raise EconomicVetoError(f"{kind} robustness screen missing")
    # A favorable additive contribution is not a capital-matched paper
    # counterfactual. Refuse positive trading claims for ALL outcomes.
    label = (
        "economic_veto_negative_after_cost_delta"
        if delta <= ZERO
        else "descriptive_screen_failed"
        if not strict
        else "descriptive_only_needs_independent_account"
    )
    return {
        "forward_original_closes": source_n,
        "hypothetically_blocked_original_closes": blocked,
        "original_booked_net_usd": str(original),
        "hypothetical_zero_replacement_booked_net_usd": str(candidate),
        "hypothetical_delta_net_usd": str(delta),
        "hypothetical_delta_net_r": str(delta_r),
        "strict_descriptive_screen_passes": strict,
        "decision": label,
        "no_replacement_trades_modeled": True,
        "full_signed_account_profitability_verified": False,
        "promotion_authority": False,
        "execution_authority": False,
    }


def review_original_forward_economics(
    *, scoreboard_zip: Path, scoreboard_sha256: str,
    short_rank_zip: Path, short_rank_sha256: str,
    entry_cost_zip: Path, entry_cost_sha256: str,
) -> dict[str, object]:
    scoreboard = _zip_json(
        scoreboard_zip, expected_sha256=scoreboard_sha256,
        member=SOURCE_MEMBER,
    )
    short = _zip_json(
        short_rank_zip, expected_sha256=short_rank_sha256,
        member=SHORT_MEMBER,
    )
    cost = _zip_json(
        entry_cost_zip, expected_sha256=entry_cost_sha256,
        member=COST_MEMBER,
    )
    return {
        "schema": "authenticated-zip-economic-decision-triage-v1",
        "original_closed_trades": _paper_overall(scoreboard),
        "frozen_short_breakout_rank": _candidate(
            short, expected="prospective-short-breakout-only-top3-v1",
            kind="short_breakout",
        ),
        "predeclared_quarter_r_entry_cost": _candidate(
            cost,
            expected="prospective-ex-ante-round-trip-cost-over-quarter-r-v1",
            kind="entry_cost",
        ),
        "different_forward_opening_cutoffs_not_combined": True,
        "three_zip_hashes_match_operator_supplied_digests": True,
        "independent_github_run_attempt_artifact_identity_verified": False,
        "strategy_or_live_order_change_authorized": False,
        "source_gap_completeness_proven": False,
        "full_signed_paper_account_profitability_proven": False,
        "paper_only": True,
        "research_only": True,
        "promotion_authority": False,
        "execution_authority": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("scoreboard", "short-rank", "entry-cost"):
        parser.add_argument(f"--{name}-zip", required=True, type=Path)
        parser.add_argument(f"--{name}-sha256", required=True)
    values = vars(parser.parse_args(argv))
    report = review_original_forward_economics(
        scoreboard_zip=values["scoreboard_zip"],
        scoreboard_sha256=values["scoreboard_sha256"],
        short_rank_zip=values["short_rank_zip"],
        short_rank_sha256=values["short_rank_sha256"],
        entry_cost_zip=values["entry_cost_zip"],
        entry_cost_sha256=values["entry_cost_sha256"],
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    # A private economic comparison is never a source or profitability cert.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
