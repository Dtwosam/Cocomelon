from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from cocomelon.research.prospective_momentum_band_forward_markout import (
    MAX_MARK_LAG_MS,
)
from cocomelon.research.prospective_risk_rejected_forward_markout_ledger import (
    ProspectiveRiskRejectedForwardMarkoutLedgerError,
    update_risk_rejected_forward_markout_ledger,
    validate_risk_rejected_forward_markout_ledger,
)

START = 100_000_000


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


def _row(
    suffix: str,
    *,
    timestamp_ms: int,
    market: str,
    decision: str,
    reason: str,
    returns: tuple[str, str, str] | None,
) -> dict[str, object]:
    block_layer = "none" if decision == "ADMIT" else "momentum"
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
        "direction": "long" if suffix.endswith("l") else "short",
        "lead_strategy": "breakout",
        "rank_ordinal": 3,
        "rank_age_ms": 100,
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": [reason],
        "combined_block_reason": None,
        "two_strike_prior_strikes": 0,
        "momentum_decision": decision,
        "momentum_reason": (
            "momentum_band_pass"
            if decision == "ADMIT"
            else "momentum_band"
        ),
        "momentum_prior_strikes": 0,
        "signed_return_1h": "0.03",
        "signed_day_return": "0.05",
        "stack_decision": decision,
        "block_layer": block_layer,
        "markouts": {
            str(horizon): _markout(
                timestamp_ms=timestamp_ms,
                horizon_ms=horizon,
                status=status,
                directional_return=value,
            )
            for horizon, status, value in zip(
                (300_000, 900_000, 3_600_000),
                statuses,
                values,
                strict=True,
            )
        },
    }


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
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
        "forward_horizons_ms": [300_000, 900_000, 3_600_000],
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "risk_rejected_stack_evaluated": len(rows),
        "risk_rejected_integrity_clean": True,
        "risk_rejected_rows": rows,
    }


def _update(
    summary: dict[str, object],
    *,
    previous: dict[str, object] | None = None,
    run_id: int = 10,
) -> dict[str, object]:
    return update_risk_rejected_forward_markout_ledger(
        summary,
        previous=previous,
        source_paper_run_id=run_id,
        source_paper_run_attempt=1,
        source_artifact_name=f"source-{run_id}",
        source_artifact_digest="sha256:" + str(run_id) * 64,
    )


def test_risk_rejected_ledger_appends_terminal_rows_and_summarizes_reason() -> None:
    first = _row(
        "first-l",
        timestamp_ms=START + 1_000,
        market="SOL",
        decision="ADMIT",
        reason="weekly_drawdown_lockout",
        returns=("0.01", "0.02", "0.03"),
    )
    second_pending = _row(
        "second-s",
        timestamp_ms=START + 2_000,
        market="ETH",
        decision="BLOCK",
        reason="weekly_drawdown_lockout",
        returns=None,
    )
    ledger = _update(_summary([first, second_pending]))

    assert ledger["row_count"] == 1
    assert ledger["new_row_count"] == 1
    assert ledger["pending_opportunity_count"] == 1
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    assert summary["risk_reason_counts"] == {
        "weekly_drawdown_lockout": 1
    }
    horizons = summary["horizons"]
    assert isinstance(horizons, dict)
    one_hour = horizons["3600000"]
    assert isinstance(one_hour, dict)
    assert one_hour["stack_admit_settled"] == 1
    admit = one_hour["stack_admit"]
    assert isinstance(admit, dict)
    assert admit["mean_directional_return"] == "0.03"
    by_reason = one_hour["by_risk_reason"]
    assert isinstance(by_reason, dict)
    weekly = by_reason["weekly_drawdown_lockout"]
    assert weekly["settled"] == 1
    assert weekly["stack_admit_settled"] == 1
    assert weekly["stack_admit_mean_directional_return"] == "0.03"

    second_terminal = _row(
        "second-s",
        timestamp_ms=START + 2_000,
        market="ETH",
        decision="BLOCK",
        reason="weekly_drawdown_lockout",
        returns=("-0.01", "-0.02", "-0.03"),
    )
    extended = _update(
        _summary([first, second_terminal]),
        previous=ledger,
        run_id=11,
    )
    assert extended["row_count"] == 2
    assert extended["previous_row_count"] == 1
    assert extended["new_row_count"] == 1
    assert extended["pending_opportunity_count"] == 0
    one_hour = extended["summary"]["horizons"]["3600000"]
    assert one_hour["stack_block_mean_directional_return"] == "-0.03"
    validate_risk_rejected_forward_markout_ledger(extended)


def test_risk_rejected_ledger_refuses_terminal_history_rewrite() -> None:
    row = _row(
        "fixed-l",
        timestamp_ms=START + 1_000,
        market="SOL",
        decision="ADMIT",
        reason="weekly_drawdown_lockout",
        returns=("0.01", "0.02", "0.03"),
    )
    ledger = _update(_summary([row]))
    changed = deepcopy(row)
    markouts = changed["markouts"]
    assert isinstance(markouts, dict)
    one_hour = markouts["3600000"]
    assert isinstance(one_hour, dict)
    one_hour["directional_return"] = "0.04"

    with pytest.raises(
        ProspectiveRiskRejectedForwardMarkoutLedgerError,
        match="previous terminal risk-rejected row changed",
    ):
        _update(
            _summary([changed]),
            previous=ledger,
            run_id=11,
        )


def test_risk_rejected_ledger_keeps_candidate_readiness_authority_off() -> None:
    row = _row(
        "authority-l",
        timestamp_ms=START + 1_000,
        market="SOL",
        decision="ADMIT",
        reason="weekly_drawdown_lockout",
        returns=("0.01", "0.02", "0.03"),
    )
    ledger = _update(_summary([row]))

    assert ledger["research_only"] is True
    assert ledger["execution_authority"] is False
    assert ledger["promotion_authority"] is False
    assert ledger["changes_risk_limits"] is False
    assert ledger["changes_candidate_readiness"] is False

    tampered = deepcopy(ledger)
    tampered["changes_risk_limits"] = True
    with pytest.raises(
        ProspectiveRiskRejectedForwardMarkoutLedgerError,
        match="authority drift",
    ):
        validate_risk_rejected_forward_markout_ledger(tampered)


def _ready_rows(
    *,
    reason: str = "weekly_drawdown_lockout",
    decision: str = "ADMIT",
    markets: tuple[str, ...] = ("SOL", "ETH", "BTC", "HYPE"),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(12):
        direction_suffix = "l" if index % 2 == 0 else "s"
        rows.append(
            _row(
                f"ready-{index}-{direction_suffix}",
                timestamp_ms=START + 10_000 + index * 1_000,
                market=markets[index % len(markets)],
                decision=decision,
                reason=reason,
                returns=("0.01", "0.012", "0.015"),
            )
        )
    return rows


def test_risk_rejected_investigation_readiness_requires_robust_stack_admits() -> None:
    ledger = _update(_summary(_ready_rows()))

    summary = ledger["summary"]
    assert isinstance(summary, dict)
    readiness = summary["risk_budget_investigation_readiness"]
    assert isinstance(readiness, dict)
    assert readiness["review_only"] is True
    assert readiness["changes_risk_limits"] is False
    assert readiness["execution_authority"] is False
    assert readiness["ready_reasons"] == ["weekly_drawdown_lockout"]

    by_reason = readiness["by_reason"]
    assert isinstance(by_reason, dict)
    weekly = by_reason["weekly_drawdown_lockout"]
    assert weekly["ready_for_risk_budget_investigation"] is True
    horizons = weekly["horizons"]
    assert isinstance(horizons, dict)
    for horizon in ("300000", "900000", "3600000"):
        item = horizons[horizon]
        assert item["stack_admit_settled"] == 12
        assert item["market_count"] == 4
        assert item["long_settled"] == 6
        assert item["short_settled"] == 6
        assert item["sample_complete"] is True
        assert item["mean_positive"] is True
        assert item["single_opportunity_robust"] is True
        assert item["single_market_robust"] is True
        assert item["ready_for_investigation"] is True


def test_risk_rejected_investigation_readiness_ignores_stack_blocks() -> None:
    rows = _ready_rows(decision="BLOCK")
    ledger = _update(_summary(rows))

    readiness = ledger["summary"]["risk_budget_investigation_readiness"]
    weekly = readiness["by_reason"]["weekly_drawdown_lockout"]
    assert weekly["ready_for_risk_budget_investigation"] is False
    for item in weekly["horizons"].values():
        assert item["stack_admit_settled"] == 0
        assert item["missing_stack_admit_settled"] == 12
        assert item["ready_for_investigation"] is False


def test_risk_rejected_investigation_readiness_rejects_market_concentration() -> None:
    rows = _ready_rows(markets=("SOL",))
    ledger = _update(_summary(rows))

    readiness = ledger["summary"]["risk_budget_investigation_readiness"]
    weekly = readiness["by_reason"]["weekly_drawdown_lockout"]
    assert weekly["ready_for_risk_budget_investigation"] is False
    for item in weekly["horizons"].values():
        assert item["market_count"] == 1
        assert item["missing_markets"] == 3
        assert item["single_market_robust"] is False
        assert item["ready_for_investigation"] is False


def test_risk_rejected_investigation_readiness_requires_clean_source() -> None:
    source = _summary(_ready_rows())
    source["risk_rejected_integrity_clean"] = False
    ledger = _update(source)

    readiness = ledger["summary"]["risk_budget_investigation_readiness"]
    assert readiness["integrity_clean"] is False
    assert readiness["ready_reasons"] == []
    weekly = readiness["by_reason"]["weekly_drawdown_lockout"]
    assert weekly["ready_for_risk_budget_investigation"] is False


def test_risk_rejected_ledger_accepts_pre_readiness_summary() -> None:
    ledger = _update(_summary(_ready_rows()))
    legacy = deepcopy(ledger)
    legacy_summary = legacy["summary"]
    assert isinstance(legacy_summary, dict)
    legacy_summary.pop("risk_budget_investigation_readiness")
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

    validated = validate_risk_rejected_forward_markout_ledger(
        legacy
    )
    assert validated["row_count"] == 12
    extended = _update(
        _summary(_ready_rows()),
        previous=legacy,
        run_id=11,
    )
    assert (
        extended["prior_ledger_sha256"]
        == legacy["ledger_sha256"]
    )
    assert (
        "risk_budget_investigation_readiness"
        in extended["summary"]
    )


def test_risk_rejected_investigation_readiness_rejects_single_outlier_edge() -> None:
    rows = _ready_rows()
    for index, row in enumerate(rows):
        markouts = row["markouts"]
        assert isinstance(markouts, dict)
        for markout in markouts.values():
            assert isinstance(markout, dict)
            markout["directional_return"] = (
                "0.50" if index == 0 else "-0.01"
            )

    ledger = _update(_summary(rows))
    readiness = ledger["summary"]["risk_budget_investigation_readiness"]
    weekly = readiness["by_reason"]["weekly_drawdown_lockout"]

    assert weekly["ready_for_risk_budget_investigation"] is False
    for item in weekly["horizons"].values():
        assert item["mean_positive"] is True
        assert item["single_opportunity_robust"] is False
        assert item["ready_for_investigation"] is False


def test_risk_rejected_investigation_readiness_requires_both_directions() -> None:
    rows = _ready_rows()
    for row in rows:
        row["direction"] = "long"

    ledger = _update(_summary(rows))
    readiness = ledger["summary"]["risk_budget_investigation_readiness"]
    weekly = readiness["by_reason"]["weekly_drawdown_lockout"]

    assert weekly["ready_for_risk_budget_investigation"] is False
    for item in weekly["horizons"].values():
        assert item["long_settled"] == 12
        assert item["short_settled"] == 0
        assert item["missing_short_settled"] == 3
        assert item["sample_complete"] is False
