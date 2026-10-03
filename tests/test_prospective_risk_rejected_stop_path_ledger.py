from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from cocomelon.research.prospective_risk_rejected_stop_path_ledger import (
    CLAIM_SCOPE,
    RiskRejectedStopPathLedgerError,
    update_risk_rejected_stop_path_ledger,
    validate_risk_rejected_stop_path_ledger,
)

START = 100_000_000
HORIZONS = (300_000, 900_000, 3_600_000)


def _stop_path(
    timestamp_ms: int,
    *,
    crossed: bool | None,
) -> dict[str, object]:
    horizons: dict[str, dict[str, object]] = {}
    for horizon in HORIZONS:
        target = timestamp_ms + horizon
        if crossed is None:
            item = {
                "status": "markout_pending",
                "target_at_ms": target,
                "observed_mark_count": 0,
                "stop_crossed": None,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": None,
            }
        elif crossed:
            item = {
                "status": "observed_stop_crossing",
                "target_at_ms": target,
                "observed_mark_count": 2,
                "stop_crossed": True,
                "first_stop_cross_at_ms": timestamp_ms + 60_000,
                "first_stop_cross_mark_px": "89",
                "time_to_stop_ms": 60_000,
                "survived_observed_marks_to_horizon": False,
            }
        else:
            item = {
                "status": "observed_path_survivor",
                "target_at_ms": target,
                "observed_mark_count": 2,
                "stop_crossed": False,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": True,
            }
        horizons[str(horizon)] = item
    return {
        "claim_scope": CLAIM_SCOPE,
        "original_stop_price": "90",
        "entry_reference_price": "100",
        "horizons": horizons,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }


def _row(
    suffix: str,
    *,
    timestamp_ms: int,
    market: str,
    layer: str,
    combined_reason: str | None,
    crossed: bool | None,
    direction: str = "long",
) -> dict[str, object]:
    decision = "ADMIT" if layer == "none" else "BLOCK"
    return {
        "opportunity_id": f"opportunity-{suffix}",
        "timestamp_ms": timestamp_ms,
        "market": market,
        "direction": direction,
        "lead_strategy": "trend",
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": ["weekly_drawdown_lockout"],
        "stack_decision": decision,
        "block_layer": layer,
        "combined_block_reason": combined_reason,
        "long_trend_carveout_stop_path": _stop_path(
            timestamp_ms,
            crossed=crossed,
        ),
    }


def _source(
    rows: list[dict[str, object]],
    *,
    integrity_clean: bool = True,
    last_miss_at_ms: int | None = None,
    include_integrity_boundary: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "overlap_started_at_ms": START,
        "risk_rejected_stack_evaluated": len(rows),
        "risk_rejected_integrity_clean": integrity_clean,
        "risk_rejected_long_trend_carveout": {
            "stop_path_overlay": {
                "enabled": True,
                "claim_scope": CLAIM_SCOPE,
                "changes_execution": False,
                "changes_risk_limits": False,
                "changes_candidate_readiness": False,
            }
        },
        "risk_rejected_rows": rows,
    }
    if include_integrity_boundary:
        payload["risk_rejected_integrity_last_miss_at_ms"] = (
            last_miss_at_ms
            if integrity_clean or last_miss_at_ms is not None
            else START
        )
    return payload


def _update(
    source: dict[str, object],
    *,
    previous: dict[str, object] | None = None,
    run_id: int = 10,
) -> dict[str, object]:
    return update_risk_rejected_stop_path_ledger(
        source,
        previous=previous,
        source_paper_run_id=run_id,
        source_paper_run_attempt=1,
        source_artifact_name=f"compact-{run_id}",
        source_artifact_digest=f"sha256:{run_id:064x}",
    )


def test_stop_path_ledger_freezes_resolved_and_keeps_pending() -> None:
    crossed = _row(
        "cross",
        timestamp_ms=START + 1_000,
        market="SOL",
        layer="combined",
        combined_reason="long_trend",
        crossed=True,
    )
    survivor = _row(
        "survive",
        timestamp_ms=START + 2_000,
        market="ETH",
        layer="momentum",
        combined_reason=None,
        crossed=False,
    )
    pending = _row(
        "pending",
        timestamp_ms=START + 3_000,
        market="BTC",
        layer="combined",
        combined_reason="rank_above_10",
        crossed=None,
    )

    ledger = _update(_source([crossed, survivor, pending]))

    assert ledger["row_count"] == 2
    assert ledger["new_row_count"] == 2
    assert ledger["pending_opportunity_count"] == 1
    summary = ledger["summary"]
    five = summary["horizons"]["300000"]
    assert five["overall"]["evaluable"] == 2
    assert five["overall"]["crossings"] == 1
    assert five["overall"]["survivors"] == 1
    assert five["overall"]["crossing_fraction"] == "0.5"
    assert five["overall"]["median_time_to_stop_ms"] == 60_000
    assert five["by_block_layer"]["combined"]["crossings"] == 1
    assert five["by_block_layer"]["momentum"]["survivors"] == 1
    assert five["by_combined_reason"]["long_trend"]["crossings"] == 1
    validate_risk_rejected_stop_path_ledger(ledger)


def _ready_stop_rows(
    *,
    crossings: int,
    start_offset_ms: int = 1,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    markets = ("SOL", "ETH", "BTC", "HYPE")
    for index in range(12):
        rows.append(
            _row(
                f"ready-{index}",
                timestamp_ms=START + start_offset_ms + index,
                market=markets[index % len(markets)],
                layer="none",
                combined_reason=None,
                crossed=index < crossings,
                direction=("long" if index % 2 == 0 else "short"),
            )
        )
    return rows


def test_stop_path_ledger_gates_risk_investigation_on_robust_survival() -> None:
    ledger = _update(_source(_ready_stop_rows(crossings=4)))
    gate = ledger["summary"]["risk_budget_stop_investigation"]

    assert gate["scope"] == (
        "risk_rejected_stack_admit_stop_survival_only"
    )
    assert gate["ready_reasons"] == ["weekly_drawdown_lockout"]
    assert gate["min_evaluable_per_horizon"] == 12
    assert gate["min_markets_per_horizon"] == 4
    assert gate["min_long_evaluable_per_horizon"] == 3
    assert gate["min_short_evaluable_per_horizon"] == 3

    reason = gate["by_reason"]["weekly_drawdown_lockout"]
    assert reason["ready_for_risk_budget_stop_investigation"] is True
    for item in reason["horizons"].values():
        assert item["evaluable"] == 12
        assert item["survivors"] == 8
        assert item["crossings"] == 4
        assert item["survival_margin"] == 4
        assert item["market_count"] == 4
        assert item["long_evaluable"] == 6
        assert item["short_evaluable"] == 6
        assert item["coverage_complete"] is True
        assert item["sample_complete"] is True
        assert item["survivor_majority"] is True
        assert item["single_opportunity_robust"] is True
        assert item["single_market_robust"] is True
        assert (
            item["ready_for_risk_budget_stop_investigation"]
            is True
        )


def test_stop_path_ledger_rejects_tied_survival_for_risk_review() -> None:
    ledger = _update(_source(_ready_stop_rows(crossings=6)))
    gate = ledger["summary"]["risk_budget_stop_investigation"]

    assert gate["ready_reasons"] == []
    reason = gate["by_reason"]["weekly_drawdown_lockout"]
    assert reason["ready_for_risk_budget_stop_investigation"] is False
    for item in reason["horizons"].values():
        assert item["survivors"] == 6
        assert item["crossings"] == 6
        assert item["survivor_majority"] is False
        assert (
            item["ready_for_risk_budget_stop_investigation"]
            is False
        )


def test_stop_path_post_integrity_cohort_starts_after_last_miss() -> None:
    old_row = _row(
        "pre-miss",
        timestamp_ms=START + 4_000,
        market="SOL",
        layer="none",
        combined_reason=None,
        crossed=False,
    )
    clean_rows = _ready_stop_rows(
        crossings=4,
        start_offset_ms=10_000,
    )
    source = _source(
        [old_row, *clean_rows],
        integrity_clean=False,
        last_miss_at_ms=START + 5_000,
    )

    ledger = _update(source)
    summary = ledger["summary"]

    assert summary["integrity_clean"] is False
    assert summary["risk_budget_stop_investigation"][
        "ready_reasons"
    ] == []
    post = summary["post_integrity_miss"]
    assert post["boundary_known"] is True
    assert post["last_miss_at_ms"] == START + 5_000
    assert post["started_at_ms"] == START + 5_001
    assert post["terminal_opportunity_count"] == 12
    readiness = post["risk_budget_stop_investigation"]
    assert readiness["ready_reasons"] == ["weekly_drawdown_lockout"]
    assert readiness["changes_risk_limits"] is False
    assert readiness["changes_execution"] is False


def test_stop_path_legacy_dirty_source_has_no_clean_boundary() -> None:
    source = _source(
        _ready_stop_rows(crossings=4),
        integrity_clean=False,
        include_integrity_boundary=False,
    )

    ledger = _update(source)
    post = ledger["summary"]["post_integrity_miss"]

    assert post["boundary_known"] is False
    assert post["started_at_ms"] is None
    assert post["risk_budget_stop_investigation"] is None


def test_stop_path_ledger_accepts_pre_stop_gate_summary() -> None:
    ledger = _update(_source(_ready_stop_rows(crossings=4)))
    legacy = deepcopy(ledger)
    summary = legacy["summary"]
    assert isinstance(summary, dict)
    summary.pop("post_integrity_miss")
    summary.pop("risk_budget_stop_investigation")

    digest_payload = {
        key: value
        for key, value in legacy.items()
        if key != "ledger_sha256"
    }
    legacy["ledger_sha256"] = hashlib.sha256(
        json.dumps(
            digest_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    validated = validate_risk_rejected_stop_path_ledger(legacy)
    assert validated["row_count"] == 12


def test_stop_path_ledger_preserves_terminal_rows() -> None:
    row = _row(
        "fixed",
        timestamp_ms=START + 1_000,
        market="SOL",
        layer="combined",
        combined_reason="long_trend",
        crossed=True,
    )
    first = _update(_source([row]))
    changed = deepcopy(row)
    stop_path = changed["long_trend_carveout_stop_path"]
    assert isinstance(stop_path, dict)
    horizons = stop_path["horizons"]
    assert isinstance(horizons, dict)
    five = horizons["300000"]
    assert isinstance(five, dict)
    five["first_stop_cross_mark_px"] = "88"

    with pytest.raises(
        RiskRejectedStopPathLedgerError,
        match="previous terminal stop-path row changed",
    ):
        _update(
            _source([changed]),
            previous=first,
            run_id=11,
        )


def test_stop_path_ledger_rejects_risk_approved_rows() -> None:
    row = _row(
        "approved",
        timestamp_ms=START + 1_000,
        market="SOL",
        layer="combined",
        combined_reason="long_trend",
        crossed=False,
    )
    row["baseline_risk_approved"] = True

    with pytest.raises(
        RiskRejectedStopPathLedgerError,
        match="risk-rejected rows only",
    ):
        _update(_source([row]))


def test_stop_path_ledger_rejects_legacy_source_without_overlay() -> None:
    source = _source([])
    source["risk_rejected_long_trend_carveout"] = {}

    with pytest.raises(
        RiskRejectedStopPathLedgerError,
        match="predates stop-path overlay",
    ):
        _update(source)


def test_stop_path_ledger_integrity_propagates_across_sources() -> None:
    row = _row(
        "integrity",
        timestamp_ms=START + 1_000,
        market="SOL",
        layer="combined",
        combined_reason="long_trend",
        crossed=False,
    )
    first = _update(_source([row], integrity_clean=True))
    second = _update(
        _source([row], integrity_clean=False),
        previous=first,
        run_id=11,
    )

    assert second["summary"]["integrity_clean"] is False


def test_stop_path_ledger_digest_detects_tampering() -> None:
    row = _row(
        "digest",
        timestamp_ms=START + 1_000,
        market="SOL",
        layer="combined",
        combined_reason="long_trend",
        crossed=False,
    )
    ledger = _update(_source([row]))
    tampered = deepcopy(ledger)
    tampered["ledger_sha256"] = hashlib.sha256(
        json.dumps({"fake": True}).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        RiskRejectedStopPathLedgerError,
        match="ledger digest mismatch",
    ):
        validate_risk_rejected_stop_path_ledger(tampered)


def test_stop_path_ledger_has_no_execution_authority() -> None:
    row = _row(
        "authority",
        timestamp_ms=START + 1_000,
        market="SOL",
        layer="combined",
        combined_reason="long_trend",
        crossed=False,
    )
    ledger = _update(_source([row]))
    assert ledger["research_only"] is True
    assert ledger["execution_authority"] is False
    assert ledger["promotion_authority"] is False
    assert ledger["changes_risk_limits"] is False
    assert ledger["changes_candidate_readiness"] is False
