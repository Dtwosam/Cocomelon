from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)
from cocomelon.research.prospective_long_trend_carveout_forward_markout_ledger import (
    ProspectiveLongTrendCarveoutLedgerError,
    update_long_trend_carveout_ledger,
    validate_long_trend_carveout_ledger,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    MAX_MARK_LAG_MS,
)

START = 100_000_000
HORIZONS = (300_000, 900_000, 3_600_000)


def _markout(
    *,
    timestamp_ms: int,
    horizon_ms: int,
    status: str,
    directional_return: str | None,
) -> dict[str, object]:
    target = timestamp_ms + horizon_ms
    if status in {"pending", "missing_path", "unsupported_horizon"}:
        return {
            "status": status,
            "target_at_ms": target,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return": None,
        }
    lag = 0 if status == "settled" else MAX_MARK_LAG_MS + 1
    return {
        "status": status,
        "target_at_ms": target,
        "observed_at_ms": target + lag,
        "observation_lag_ms": lag,
        "mark_px": "101",
        "directional_return": (
            directional_return if status == "settled" else None
        ),
    }


def _stop_path(
    *,
    timestamp_ms: int,
    crossed: bool,
) -> dict[str, object]:
    horizons: dict[str, dict[str, object]] = {}
    for horizon in HORIZONS:
        target = timestamp_ms + horizon
        if crossed:
            horizons[str(horizon)] = {
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
            horizons[str(horizon)] = {
                "status": "observed_path_survivor",
                "target_at_ms": target,
                "observed_mark_count": 2,
                "stop_crossed": False,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": True,
            }
    return {
        "claim_scope": "observed_mark_stop_crossing_only",
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
    direction: str,
    combined_reason: str,
    carveout_decision: str,
    returns: tuple[str, str, str] | None,
) -> dict[str, object]:
    if combined_reason == "long_trend":
        original_decision = "BLOCK"
        original_layer = "combined"
        carveout_layer = (
            "none" if carveout_decision == "ADMIT" else "momentum"
        )
        lead_strategy = "trend"
        rank_ordinal = 3
        momentum_decision = carveout_decision
        momentum_reason = (
            "momentum_band_pass"
            if carveout_decision == "ADMIT"
            else "momentum_band"
        )
    else:
        original_decision = "BLOCK"
        original_layer = "combined"
        carveout_decision = "BLOCK"
        carveout_layer = "rank_above_10"
        lead_strategy = "breakout"
        rank_ordinal = 12
        momentum_decision = None
        momentum_reason = None

    statuses = (
        ("pending", "pending", "pending")
        if returns is None
        else ("settled", "settled", "settled")
    )
    values = returns or ("0", "0", "0")
    return {
        "opportunity_id": f"opportunity-{suffix}",
        "timestamp_ms": timestamp_ms,
        "market": market,
        "direction": direction,
        "lead_strategy": lead_strategy,
        "rank_ordinal": rank_ordinal,
        "rank_age_ms": 100,
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": ["weekly_drawdown_lockout"],
        "combined_block_reason": combined_reason,
        "two_strike_prior_strikes": 0,
        "stack_decision": original_decision,
        "block_layer": original_layer,
        "long_trend_carveout_candidate_id": (
            LONG_TREND_CARVEOUT_CANDIDATE_ID
        ),
        "long_trend_carveout_decision": carveout_decision,
        "long_trend_carveout_block_layer": carveout_layer,
        "long_trend_carveout_momentum_decision": momentum_decision,
        "long_trend_carveout_momentum_reason": momentum_reason,
        "long_trend_carveout_momentum_prior_strikes": (
            0 if momentum_decision is not None else None
        ),
        "long_trend_carveout_signed_return_1h": (
            "0.03" if momentum_decision is not None else None
        ),
        "long_trend_carveout_signed_day_return": (
            "0.05" if momentum_decision is not None else None
        ),
        "markouts": {
            str(horizon): _markout(
                timestamp_ms=timestamp_ms,
                horizon_ms=horizon,
                status=status,
                directional_return=value,
            )
            for horizon, status, value in zip(
                HORIZONS,
                statuses,
                values,
                strict=True,
            )
        },
    }


def _summary(
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
        "candidate_stack": "combined+two_strike+momentum",
        "overlap_started_at_ms": START,
        "combined_started_at_ms": START - 2_000,
        "two_strike_started_at_ms": START - 1_000,
        "momentum_started_at_ms": START,
        "forward_horizons_ms": list(HORIZONS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "risk_rejected_stack_evaluated": len(rows),
        "risk_rejected_integrity_clean": True,
        "risk_rejected_long_trend_carveout": {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "descriptive_only": True,
            "changes_readiness_gate": False,
            "changes_closed_trade_readiness_gate": False,
            "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
            "stop_path_overlay": {
                "enabled": True,
                "claim_scope": "observed_mark_stop_crossing_only",
                "changes_execution": False,
                "changes_risk_limits": False,
                "changes_candidate_readiness": False,
            },
            "evaluated": len(rows),
            "admitted": sum(
                row["long_trend_carveout_decision"] == "ADMIT"
                for row in rows
            ),
            "blocked": sum(
                row["long_trend_carveout_decision"] == "BLOCK"
                for row in rows
            ),
            "integrity_clean": integrity_clean,
        },
        "risk_rejected_rows": rows,
    }
    if include_integrity_boundary:
        payload[
            "risk_rejected_long_trend_carveout_integrity_last_miss_at_ms"
        ] = last_miss_at_ms
    return payload


def _update(
    summary: dict[str, object],
    *,
    previous: dict[str, object] | None = None,
    run_id: int = 10,
) -> dict[str, object]:
    return update_long_trend_carveout_ledger(
        summary,
        previous=previous,
        source_paper_run_id=run_id,
        source_paper_run_attempt=1,
        source_artifact_name=f"source-{run_id}",
        source_artifact_digest="sha256:" + str(run_id) * 64,
    )


def test_carveout_ledger_appends_terminal_and_keeps_pending_unfrozen() -> None:
    terminal = _row(
        "admit",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    pending = _row(
        "pending",
        timestamp_ms=START + 2_000,
        market="ETH",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=None,
    )
    ledger = _update(_summary([terminal, pending]))

    assert ledger["row_count"] == 1
    assert ledger["new_row_count"] == 1
    assert ledger["pending_opportunity_count"] == 1
    summary = ledger["summary"]
    assert summary["carveout_admitted_terminal"] == 1
    assert summary["reopened_long_trend_terminal"] == 1
    one_hour = summary["horizons"]["3600000"]
    assert one_hour["reopened_long_trend_settled"] == 1
    assert one_hour["reopened_long_trend"][
        "mean_directional_return"
    ] == "0.03"
    assert (
        one_hour["investigation_readiness"][
            "ready_for_execution_shadow_investigation"
        ]
        is False
    )
    validate_long_trend_carveout_ledger(ledger)


def test_carveout_ledger_reports_stop_path_survival() -> None:
    row = _row(
        "stop-survivor",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    row["long_trend_carveout_stop_path"] = _stop_path(
        timestamp_ms=START + 1_000,
        crossed=False,
    )

    ledger = _update(_summary([row]))
    one_hour = ledger["summary"]["horizons"]["3600000"]
    stop = one_hour["reopened_long_trend_stop_path"]
    assert stop["claim_scope"] == "observed_mark_stop_crossing_only"
    assert stop["evaluable"] == 1
    assert stop["crossings"] == 0
    assert stop["survivors"] == 1
    assert stop["crossing_fraction"] == "0"
    assert stop["median_time_to_stop_ms"] is None
    assert (
        one_hour["investigation_readiness"][
            "ready_for_execution_shadow_investigation"
        ]
        is False
    )
    validate_long_trend_carveout_ledger(ledger)


def test_carveout_ledger_reports_stop_path_crossing() -> None:
    row = _row(
        "stop-cross",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    row["long_trend_carveout_stop_path"] = _stop_path(
        timestamp_ms=START + 1_000,
        crossed=True,
    )

    ledger = _update(_summary([row]))
    five_minute = ledger["summary"]["horizons"]["300000"]
    stop = five_minute["reopened_long_trend_stop_path"]
    assert stop["evaluable"] == 1
    assert stop["crossings"] == 1
    assert stop["survivors"] == 0
    assert stop["crossing_fraction"] == "1"
    assert stop["median_time_to_stop_ms"] == 60_000


def test_carveout_ledger_reports_reopened_exit_timing() -> None:
    first = _row(
        "timing-sol",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.03", "0.04", "0.01"),
    )
    second = _row(
        "timing-eth",
        timestamp_ms=START + 2_000,
        market="ETH",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.02", "0.03", "0.00"),
    )

    ledger = _update(_summary([first, second]))
    timing = ledger["summary"]["reopened_long_trend_exit_timing"]

    assert timing["claim_scope"] == "fixed_markout_exit_timing_only"
    assert timing["evaluable_opportunities"] == 2
    assert timing["market_count"] == 2
    assert timing["best_horizon_counts"] == {"900000": 2}
    assert timing["best_horizon_ties"] == 0
    assert timing["early_exit_preferred_count"] == 2
    assert timing["sixty_min_preferred_count"] == 0
    assert timing["early_vs_sixty_tie_count"] == 0
    assert (
        timing["five_min_minus_sixty_min"][
            "mean_directional_return"
        ]
        == "0.02"
    )
    assert (
        timing["fifteen_min_minus_sixty_min"][
            "mean_directional_return"
        ]
        == "0.03"
    )
    assert (
        timing["five_min_minus_fifteen_min"][
            "mean_directional_return"
        ]
        == "-0.01"
    )
    assert timing["changes_execution"] is False
    assert timing["changes_risk_limits"] is False
    assert timing["changes_candidate_readiness"] is False


def test_carveout_ledger_accepts_pre_exit_timing_summary() -> None:
    row = _row(
        "legacy-timing",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    ledger = _update(_summary([row]))
    legacy = deepcopy(ledger)
    summary = legacy["summary"]
    assert isinstance(summary, dict)
    summary.pop("reopened_long_trend_exit_timing")

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

    validated = validate_long_trend_carveout_ledger(legacy)
    assert validated["row_count"] == 1


def test_carveout_ledger_accepts_pre_stop_path_summary() -> None:
    row = _row(
        "legacy-stop",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    ledger = _update(_summary([row]))
    legacy = deepcopy(ledger)
    summary = legacy["summary"]
    assert isinstance(summary, dict)
    summary.pop("post_integrity_miss")
    summary.pop(
        "effective_all_horizons_ready_for_execution_shadow_investigation"
    )
    summary.pop("effective_integrity_scope")
    horizons = summary["horizons"]
    assert isinstance(horizons, dict)
    for item in horizons.values():
        assert isinstance(item, dict)
        item.pop("reopened_long_trend_stop_path")
        readiness = item["investigation_readiness"]
        assert isinstance(readiness, dict)
        for key in (
            "stop_path_complete_for_reopened_sample",
            "stop_survivor_majority",
            "stop_evaluable",
            "stop_crossings",
            "stop_survivors",
        ):
            readiness.pop(key)

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

    validated = validate_long_trend_carveout_ledger(legacy)
    assert validated["row_count"] == 1


def test_carveout_ledger_accepts_pre_stop_readiness_summary() -> None:
    ledger = _update(
        _summary(_ready_economic_rows(stop_crossings=4))
    )
    legacy = deepcopy(ledger)
    summary = legacy["summary"]
    assert isinstance(summary, dict)
    summary.pop("post_integrity_miss")
    summary.pop(
        "effective_all_horizons_ready_for_execution_shadow_investigation"
    )
    summary.pop("effective_integrity_scope")
    horizons = summary["horizons"]
    assert isinstance(horizons, dict)
    for item in horizons.values():
        assert isinstance(item, dict)
        readiness = item["investigation_readiness"]
        assert isinstance(readiness, dict)
        for key in (
            "stop_path_complete_for_reopened_sample",
            "stop_survivor_majority",
            "stop_evaluable",
            "stop_crossings",
            "stop_survivors",
        ):
            readiness.pop(key)
        readiness["ready_for_execution_shadow_investigation"] = True
    summary[
        "all_horizons_ready_for_execution_shadow_investigation"
    ] = True

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

    validated = validate_long_trend_carveout_ledger(legacy)
    assert validated["row_count"] == 20


def test_carveout_ledger_refuses_terminal_history_rewrite() -> None:
    row = _row(
        "fixed",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    first = _update(_summary([row]))
    changed = deepcopy(row)
    markouts = changed["markouts"]
    assert isinstance(markouts, dict)
    one_hour = markouts["3600000"]
    assert isinstance(one_hour, dict)
    one_hour["directional_return"] = "0.04"

    with pytest.raises(
        ProspectiveLongTrendCarveoutLedgerError,
        match="previous terminal carveout row changed",
    ):
        _update(
            _summary([changed]),
            previous=first,
            run_id=11,
        )


def test_carveout_ledger_rejects_rank_block_becoming_admit() -> None:
    row = _row(
        "rank",
        timestamp_ms=START + 1_000,
        market="ETH",
        direction="short",
        combined_reason="rank_above_10",
        carveout_decision="BLOCK",
        returns=("-0.01", "-0.02", "-0.03"),
    )
    row["long_trend_carveout_decision"] = "ADMIT"
    row["long_trend_carveout_block_layer"] = "none"

    with pytest.raises(
        ProspectiveLongTrendCarveoutLedgerError,
        match="rank block changed",
    ):
        _update(_summary([row]))


def _ready_economic_rows(
    *,
    stop_crossings: int | None,
    timestamp_offset_ms: int = 0,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    markets = ("SOL", "ETH", "BTC", "HYPE")
    for index in range(10):
        row = _row(
            f"reopen-{index}",
            timestamp_ms=START + timestamp_offset_ms + index + 1,
            market=markets[index % len(markets)],
            direction="long",
            combined_reason="long_trend",
            carveout_decision="ADMIT",
            returns=("0.01", "0.02", "0.03"),
        )
        if stop_crossings is not None:
            row["long_trend_carveout_stop_path"] = _stop_path(
                timestamp_ms=START + timestamp_offset_ms + index + 1,
                crossed=index < stop_crossings,
            )
        rows.append(row)
    for index in range(10):
        rows.append(
            _row(
                f"block-{index}",
                timestamp_ms=START + timestamp_offset_ms + 100 + index,
                market=markets[index % len(markets)],
                direction="short",
                combined_reason="rank_above_10",
                carveout_decision="BLOCK",
                returns=("-0.01", "-0.02", "-0.03"),
            )
        )
    return rows


def test_carveout_ledger_post_integrity_suffix_reearns_full_gate() -> None:
    dirty = _row(
        "pre-integrity-miss",
        timestamp_ms=START + 10,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("-0.20", "-0.20", "-0.20"),
    )
    dirty["long_trend_carveout_stop_path"] = _stop_path(
        timestamp_ms=START + 10,
        crossed=True,
    )
    clean = _ready_economic_rows(
        stop_crossings=4,
        timestamp_offset_ms=1_000,
    )
    source = _summary(
        [dirty, *clean],
        integrity_clean=False,
        last_miss_at_ms=START + 500,
    )

    ledger = _update(source)
    summary = ledger["summary"]

    assert summary["integrity_clean"] is False
    assert (
        summary[
            "all_horizons_ready_for_execution_shadow_investigation"
        ]
        is False
    )
    post = summary["post_integrity_miss"]
    assert post["boundary_known"] is True
    assert post["last_miss_at_ms"] == START + 500
    assert post["started_at_ms"] == START + 501
    assert post["terminal_opportunity_count"] == 20
    assert (
        post[
            "all_horizons_ready_for_execution_shadow_investigation"
        ]
        is True
    )
    assert (
        summary[
            "effective_all_horizons_ready_for_execution_shadow_investigation"
        ]
        is True
    )
    assert summary["effective_integrity_scope"] == "post_integrity_miss"
    assert ledger["source_history"][-1][
        "integrity_last_miss_at_ms"
    ] == START + 500
    for item in post["horizons"].values():
        readiness = item["investigation_readiness"]
        assert readiness["integrity_clean"] is True
        assert readiness["sample_complete"] is True
        assert readiness["reopened_sample_complete"] is True
        assert readiness["reopened_robust"] is True
        assert readiness["stop_path_complete_for_reopened_sample"] is True
        assert readiness["stop_survivor_majority"] is True
    validate_long_trend_carveout_ledger(ledger)


def test_carveout_ledger_dirty_legacy_source_cannot_claim_clean_suffix() -> None:
    source = _summary(
        _ready_economic_rows(stop_crossings=4),
        integrity_clean=False,
        include_integrity_boundary=False,
    )

    ledger = _update(source)
    summary = ledger["summary"]
    post = summary["post_integrity_miss"]

    assert summary["integrity_clean"] is False
    assert post["boundary_known"] is False
    assert post["started_at_ms"] is None
    assert post["terminal_opportunity_count"] == 0
    assert (
        post[
            "all_horizons_ready_for_execution_shadow_investigation"
        ]
        is False
    )
    assert (
        summary[
            "effective_all_horizons_ready_for_execution_shadow_investigation"
        ]
        is False
    )
    assert summary["effective_integrity_scope"] == "none"


def test_carveout_ledger_ready_only_with_stop_survivor_majority() -> None:
    ledger = _update(
        _summary(_ready_economic_rows(stop_crossings=4))
    )
    summary = ledger["summary"]
    assert (
        summary[
            "all_horizons_ready_for_execution_shadow_investigation"
        ]
        is True
    )
    for item in summary["horizons"].values():
        readiness = item["investigation_readiness"]
        assert (
            readiness["ready_for_execution_shadow_investigation"]
            is True
        )
        assert (
            readiness["stop_path_complete_for_reopened_sample"]
            is True
        )
        assert readiness["stop_survivor_majority"] is True
        assert readiness["stop_evaluable"] == 10
        assert readiness["stop_crossings"] == 4
        assert readiness["stop_survivors"] == 6
        assert readiness["changes_execution"] is False
        assert readiness["changes_risk_limits"] is False
        assert readiness["changes_candidate_readiness"] is False


def test_carveout_ledger_not_ready_without_stop_path_coverage() -> None:
    ledger = _update(
        _summary(_ready_economic_rows(stop_crossings=None))
    )
    for item in ledger["summary"]["horizons"].values():
        readiness = item["investigation_readiness"]
        assert (
            readiness["ready_for_execution_shadow_investigation"]
            is False
        )
        assert (
            readiness["stop_path_complete_for_reopened_sample"]
            is False
        )
        assert readiness["stop_survivor_majority"] is False
        assert readiness["stop_evaluable"] == 0


def test_carveout_ledger_not_ready_without_survivor_majority() -> None:
    ledger = _update(
        _summary(_ready_economic_rows(stop_crossings=5))
    )
    for item in ledger["summary"]["horizons"].values():
        readiness = item["investigation_readiness"]
        assert (
            readiness["ready_for_execution_shadow_investigation"]
            is False
        )
        assert (
            readiness["stop_path_complete_for_reopened_sample"]
            is True
        )
        assert readiness["stop_survivor_majority"] is False
        assert readiness["stop_crossings"] == 5
        assert readiness["stop_survivors"] == 5


def test_carveout_ledger_authority_drift_fails_closed() -> None:
    row = _row(
        "authority",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    ledger = _update(_summary([row]))
    tampered = deepcopy(ledger)
    tampered["execution_authority"] = True

    with pytest.raises(
        ProspectiveLongTrendCarveoutLedgerError,
        match="authority drift",
    ):
        validate_long_trend_carveout_ledger(tampered)


def test_carveout_ledger_digest_detects_tampering() -> None:
    row = _row(
        "digest",
        timestamp_ms=START + 1_000,
        market="SOL",
        direction="long",
        combined_reason="long_trend",
        carveout_decision="ADMIT",
        returns=("0.01", "0.02", "0.03"),
    )
    ledger = _update(_summary([row]))
    tampered = deepcopy(ledger)
    tampered["ledger_sha256"] = hashlib.sha256(
        json.dumps({"fake": True}).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        ProspectiveLongTrendCarveoutLedgerError,
        match="ledger digest mismatch",
    ):
        validate_long_trend_carveout_ledger(tampered)
