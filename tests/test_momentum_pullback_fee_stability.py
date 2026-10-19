from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.momentum_pullback_fee_stability import (
    MomentumPullbackFeeStressError,
    audit_momentum_pullback_optimistic_fee_stability,
)
from scripts.audit_momentum_pullback_fee_stability import main

HORIZONS = (300_000, 900_000, 3_600_000)
START = 1_792_000_000_000


def _report(
    gross: tuple[str, ...],
    *,
    markets: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP"),
    sides: tuple[str, ...] = ("long", "short"),
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for i, ret in enumerate(gross):
        timestamp = START + 100 + i * 10_000
        rows.append({
            "timestamp_ms": timestamp,
            "opportunity_id": f"opportunity-{i:04d}",
            "market": markets[i % len(markets)],
            "direction": sides[i % len(sides)],
            "pullback_decision": "ADMIT",
            "markouts": {
                str(h): {
                    "status": "settled",
                    "target_at_ms": timestamp + h,
                    "directional_return": ret,
                } for h in HORIZONS
            },
        })
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "integrity_clean": True,
        "candidate_id": "frozen-original-v1",
        "started_at_ms": START,
        "forward_horizons_ms": list(HORIZONS),
        "pullback_admitted": len(rows),
        "risk_approved_evaluated": len(rows),
        "rows": rows,
    }


def test_exact_long_and_short_exit_fee_notional_and_all_horizons() -> None:
    report = audit_momentum_pullback_optimistic_fee_stability(
        _report(("0.02", "0.02")),
    )
    assert list(report["horizons"]) == [str(h) for h in HORIZONS]
    block = report["horizons"]["3600000"]
    # Long exit notional 1.02, short exit notional 0.98.
    # Fees use two legs, not a naive twice-entry-notional charge.
    expected_long = 0.02 - 0.00045 * (1 + 1.02)
    expected_short = 0.02 - 0.00045 * (1 + 0.98)
    assert float(
        block["optimistic_fee_only"]["optimistic_fee_only_mean_net_return"]
    ) == pytest.approx((expected_long + expected_short) / 2)
    assert block["sample_sufficient"] is False
    assert block["conditional_mark_only_stress_pass"] is False
    assert report["all_original_source_continuity_verified"] is False
    assert report["funding_and_executable_book_costs_verified"] is False
    assert report["independent_capital_matched_paper_verified"] is False
    assert report["positive_absolute_after_cost_equity_verified"] is False
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["live_orders"] is False


def test_earliest_loss_and_market_dependence_undercut_positive_mean() -> None:
    # Synthetic version of the actual discovered problem: a winner-heavy
    # later cohort can still contain an early failure and market fragility.
    gross = (
        "-0.05", "-0.02", "-0.01", "-0.01",
        "0.03", "0.02", "0.02", "0.02",
        "0.02", "0.02", "0.02", "0.02",
        "0.01", "0.01", "0.01", "0.01",
    )
    report = audit_momentum_pullback_optimistic_fee_stability(
        _report(gross, markets=("GRASS", "XRP", "ETH", "SOL")),
    )
    one_hour = report["horizons"]["3600000"]
    assert float(
        one_hour["optimistic_fee_only"]["optimistic_fee_only_mean_net_return"]
    ) > 0
    assert one_hour["chronological_blocks"][0][
        "strictly_positive_complete_block"
    ] is False
    assert one_hour["all_chronological_blocks_positive"] is False
    assert one_hour["sample_sufficient"] is False
    assert one_hour["conditional_mark_only_stress_pass"] is False
    assert len(one_hour["leave_one_market_out"]) == 4


def test_even_40_perfect_hypothetical_markouts_cannot_be_promoted() -> None:
    result = audit_momentum_pullback_optimistic_fee_stability(
        _report(("0.003",) * 40),
    )
    for horizon in result["horizons"].values():
        assert horizon["sample_sufficient"] is True
        assert horizon["all_chronological_blocks_positive"] is True
        assert not horizon["nonpositive_or_incomplete_market_omissions"]
        assert horizon["conditional_mark_only_stress_pass"] is True
        assert horizon["eligible_for_strategy_promotion"] is False
    assert result["positive_absolute_after_cost_equity_verified"] is False


def test_unsettled_rows_stay_in_denominator_and_fail_closed() -> None:
    source = _report(("0.01",) * 40)
    rows = source["rows"]
    assert isinstance(rows, list)
    markouts = rows[0]["markouts"]
    assert isinstance(markouts, dict)
    markouts["3600000"]["status"] = "stale"
    markouts["3600000"]["directional_return"] = None
    report = audit_momentum_pullback_optimistic_fee_stability(source)
    one_hour = report["horizons"]["3600000"]
    assert one_hour["admitted"] == 40
    assert one_hour["optimistic_fee_only"]["settled"] == 39
    assert one_hour["optimistic_fee_only"]["missing"] == 1
    assert one_hour["conditional_mark_only_stress_pass"] is False
    assert one_hour["chronological_blocks"][0][
        "strictly_positive_complete_block"
    ] is False


@pytest.mark.parametrize("field, value, pattern", [
    ("integrity_clean", False, "feature integrity"),
    ("promotion_authority", True, "research-only"),
    ("forward_horizons_ms", [3600000], "frozen forward horizons"),
    ("pullback_admitted", 99, "admission count"),
    ("risk_approved_evaluated", 99, "evaluated row count"),
])
def test_tampered_original_summary_rejected(
    field: str, value: object, pattern: str,
) -> None:
    raw = _report(("0.01",) * 40)
    raw[field] = value
    with pytest.raises(MomentumPullbackFeeStressError, match=pattern):
        audit_momentum_pullback_optimistic_fee_stability(raw)


def test_original_markout_clocks_and_finite_return_protected() -> None:
    for field, value, reason in [
        ("target_at_ms", START + 23, "frozen target"),
        ("directional_return", "NaN", "finite"),
        ("directional_return", "Infinity", "finite"),
        ("directional_return", "1.5", "nonpositive exit price"),
    ]:
        source = _report(("0.01",), sides=("short",))
        markouts = source["rows"][0]["markouts"]
        markouts["3600000"][field] = value
        with pytest.raises(MomentumPullbackFeeStressError, match=reason):
            audit_momentum_pullback_optimistic_fee_stability(source)


def test_duplicate_original_opportunity_rejected() -> None:
    raw = _report(("0.01", "0.02"))
    raw["rows"][1]["opportunity_id"] = raw["rows"][0]["opportunity_id"]
    raw["rows"][1]["timestamp_ms"] = raw["rows"][0]["timestamp_ms"]
    with pytest.raises(MomentumPullbackFeeStressError):
        audit_momentum_pullback_optimistic_fee_stability(raw)


def test_offline_cli_keeps_source_fingerprint_and_no_profit_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    raw = _report(("0.002",) * 40)
    source = tmp_path / "frozen-original.json"
    dest = tmp_path / "fee-stress.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    assert main([str(source), "--json-out", str(dest)]) == 0
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(dest.read_text(encoding="utf-8"))
    assert saved["candidate_id"] == printed["candidate_id"]
    assert len(saved["local_source_summary_sha256"]) == 64
    assert saved["execution_authority"] is False
    assert saved["promotion_authority"] is False
    assert saved["positive_absolute_after_cost_equity_verified"] is False
