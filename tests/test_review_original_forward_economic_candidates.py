"""Economically adverse candidates must not become positive paper evidence."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.review_original_forward_economic_candidates import (
    CASH_ROUNDING,
    COST_MEMBER,
    SHORT_MEMBER,
    SOURCE_MEMBER,
    EconomicVetoError,
    main,
    review_original_forward_economics,
)


def _score() -> dict[str, object]:
    return {
        "kind": "entire-original-paper-profitability-attribution",
        "source_authentication": "caller_must_verify_github_artifact_run_attempt_digest",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_strategy_promotion": False,
        "overall": {
            "trades": 4,
            "gross_realized_pnl": "10",
            "fees": "12",
            "funding_cash_pnl": "-1",
            "net_pnl": "-3",
            "net_r": "-1.5",
            "incomplete_chart_trades": 2,
        },
        "side_cohorts": [
            {
                "cohort": {"side": "long"},
                "trades": 2,
                "gross_realized_pnl": "5",
                "fees": "6",
                "funding_cash_pnl": "-0.5",
                "net_pnl": "-1.5",
                "net_r": "-0.75",
            },
            {
                "cohort": {"side": "short"},
                "trades": 2,
                "gross_realized_pnl": "5",
                "fees": "6",
                "funding_cash_pnl": "-0.5",
                "net_pnl": "-1.5",
                "net_r": "-0.75",
            },
        ],
    }


def _short() -> dict[str, object]:
    return {
        "candidate_id": "prospective-short-breakout-only-top3-v1",
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "strict_descriptive_screen_passes": False,
        "original_forward_closed_trades": 3,
        "scored_forward_closed_trades": 3,
        "overall": {
            "trades": 3,
            "skipped": 1,
            "skipped_original_winners": 0,
            "skipped_original_losers": 1,
            "skipped_original_net_pnl": "-0.25",
            "original_net_pnl": "2",
            "candidate_skip_only_net_pnl": "2.25",
            "candidate_minus_original_net_pnl": "0.25",
            "candidate_minus_original_net_r": "0.1",
        },
        "by_direction": {
            "long": {
                "trades": 1,
                "skipped": 0,
                "original_net_pnl": "1",
                "candidate_skip_only_net_pnl": "1",
                "candidate_minus_original_net_pnl": "0",
                "candidate_minus_original_net_r": "0",
            },
            "short": {
                "trades": 2,
                "skipped": 1,
                "original_net_pnl": "1",
                "candidate_skip_only_net_pnl": "1.25",
                "candidate_minus_original_net_pnl": "0.25",
                "candidate_minus_original_net_r": "0.1",
            },
        },
    }


def _cost() -> dict[str, object]:
    return {
        "candidate_id": "prospective-ex-ante-round-trip-cost-over-quarter-r-v1",
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "strict_descriptive_screen_passes": False,
        "closed_prospective_trades": 3,
        "hypothetically_blocked_trades": 2,
        "retained_trades": 1,
        "blocked_actual_winners": 0,
        "blocked_actual_losers": 2,
        "overall": {
            "actual_net_pnl": "15",
            "candidate_net_pnl": "-5",
            "delta_net_pnl": "-20",
            "delta_net_r": "-1.1",
        },
        "by_direction": {
            "long": {
                "retained_trades": 1,
                "blocked_trades": 1,
                "actual_net_pnl": "5",
                "candidate_net_pnl": "-4",
                "delta_net_pnl": "-9",
                "delta_net_r": "-0.5",
            },
            "short": {
                "retained_trades": 0,
                "blocked_trades": 1,
                "actual_net_pnl": "10",
                "candidate_net_pnl": "-1",
                "delta_net_pnl": "-11",
                "delta_net_r": "-0.6",
            },
        },
    }


def _zip(path: Path, member: str, data: dict[str, object]) -> str:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, json.dumps(data, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs(
    tmp_path: Path,
    *, source: dict[str, object] | None = None,
    short: dict[str, object] | None = None,
    cost: dict[str, object] | None = None,
) -> dict[str, object]:
    a, b, c = (tmp_path / "a.zip", tmp_path / "b.zip", tmp_path / "c.zip")
    return {
        "scoreboard_zip": a,
        "scoreboard_sha256": _zip(a, SOURCE_MEMBER, source or _score()),
        "short_rank_zip": b,
        "short_rank_sha256": _zip(b, SHORT_MEMBER, short or _short()),
        "entry_cost_zip": c,
        "entry_cost_sha256": _zip(c, COST_MEMBER, cost or _cost()),
    }


def test_adverse_entry_cost_and_weak_rank_are_distinct_unpromotable(
    tmp_path: Path,
) -> None:
    args = _inputs(tmp_path)
    originals = {p: p.read_bytes() for p in tmp_path.iterdir()}
    receipt = review_original_forward_economics(**args)
    whole = receipt["original_closed_trades"]
    assert whole["closes"] == 4
    assert whole["fees_usd"] == "12"
    assert whole["after_cost_closed_net_usd"] == "-3"
    assert whole["fee_drag_exceeds_gross"] is True
    cost = receipt["predeclared_quarter_r_entry_cost"]
    assert cost["hypothetically_blocked_original_closes"] == 2
    assert cost["hypothetical_delta_net_usd"] == "-20"
    assert cost["decision"] == "economic_veto_negative_after_cost_delta"
    short = receipt["frozen_short_breakout_rank"]
    assert short["decision"] == "descriptive_screen_failed"
    assert short["hypothetical_delta_net_usd"] == "0.25"
    assert receipt["different_forward_opening_cutoffs_not_combined"] is True
    for field in (
        "independent_github_run_attempt_artifact_identity_verified",
        "strategy_or_live_order_change_authorized",
        "source_gap_completeness_proven",
        "full_signed_paper_account_profitability_proven",
        "execution_authority",
        "promotion_authority",
    ):
        assert receipt[field] is False
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == originals


def test_cli_even_on_clean_arithmetic_can_never_return_a_qualifying_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    args = _inputs(tmp_path)
    argv: list[str] = []
    for prefix, key, digest in (
        ("scoreboard", "scoreboard_zip", "scoreboard_sha256"),
        ("short-rank", "short_rank_zip", "short_rank_sha256"),
        ("entry-cost", "entry_cost_zip", "entry_cost_sha256"),
    ):
        argv.extend([f"--{prefix}-zip", str(args[key])])
        argv.extend([f"--{prefix}-sha256", str(args[digest])])
    assert main(argv) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["research_only"] is True
    assert report["strategy_or_live_order_change_authorized"] is False


def test_tampered_original_archive_never_enters_decision(
    tmp_path: Path,
) -> None:
    args = _inputs(tmp_path)
    target = args["scoreboard_zip"]
    assert isinstance(target, Path)
    target.write_bytes(target.read_bytes() + b"unsourced")
    with pytest.raises(EconomicVetoError, match="SHA256 mismatch"):
        review_original_forward_economics(**args)


@pytest.mark.parametrize("mutate", [
    lambda x: x["overall"].update({"net_pnl": "100"}),
    lambda x: x["overall"].update({"gross_realized_pnl": "Infinity"}),
    lambda x: x["overall"].update({"fees": "-10"}),
    lambda x: x.update({"execution_authority": True}),
    lambda x: x["side_cohorts"][0].update({"net_pnl": "100"}),
    lambda x: x["overall"].update({"incomplete_chart_trades": 5}),
])
def test_original_closes_or_costs_cannot_be_laundered(
    tmp_path: Path, mutate: object,
) -> None:
    source = _score()
    mutate(source)
    with pytest.raises(EconomicVetoError):
        review_original_forward_economics(**_inputs(tmp_path, source=source))


def test_candidate_gain_must_match_original_booked_trade_cash(
    tmp_path: Path,
) -> None:
    short = _short()
    short["overall"]["skipped_original_net_pnl"] = "-9"
    with pytest.raises(EconomicVetoError, match="contribution invalid"):
        review_original_forward_economics(**_inputs(tmp_path, short=short))


def test_forged_cost_delta_is_rejected_even_if_source_is_negative(
    tmp_path: Path,
) -> None:
    cost = _cost()
    cost["overall"]["delta_net_pnl"] = "20"
    with pytest.raises(EconomicVetoError, match="contribution invalid"):
        review_original_forward_economics(**_inputs(tmp_path, cost=cost))


def test_future_positive_strict_screen_is_not_full_account_certification(
    tmp_path: Path,
) -> None:
    short = _short()
    short["strict_descriptive_screen_passes"] = True
    cost = _cost()
    cost["strict_descriptive_screen_passes"] = True
    cost["overall"] = {
        "actual_net_pnl": "-5",
        "candidate_net_pnl": "1",
        "delta_net_pnl": "6",
        "delta_net_r": "0.4",
    }
    cost["by_direction"] = {
        "long": {
            "retained_trades": 1,
            "blocked_trades": 1,
            "actual_net_pnl": "-3",
            "candidate_net_pnl": "1",
            "delta_net_pnl": "4",
            "delta_net_r": "0.3",
        },
        "short": {
            "retained_trades": 0,
            "blocked_trades": 1,
            "actual_net_pnl": "-2",
            "candidate_net_pnl": "0",
            "delta_net_pnl": "2",
            "delta_net_r": "0.1",
        },
    }
    receipt = review_original_forward_economics(
        **_inputs(tmp_path, short=short, cost=cost)
    )
    assert receipt["frozen_short_breakout_rank"]["decision"] == (
        "descriptive_only_needs_independent_account"
    )
    assert receipt["predeclared_quarter_r_entry_cost"]["decision"] == (
        "descriptive_only_needs_independent_account"
    )
    assert receipt["promotion_authority"] is False


def test_exact_cash_rounding_limit_is_explicit() -> None:
    assert str(CASH_ROUNDING) == "1E-18"
