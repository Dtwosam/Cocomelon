from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.prospective_cutover_acceptance as cutover_module
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_blind_monitor import (
    BlindBlockHealth,
    ProspectiveBlindMonitor,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveCampaignManifest,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_cutover_acceptance import (
    ProspectiveCutoverAcceptanceError,
    build_prospective_hype_cutover_acceptance,
    verify_prospective_hype_cutover_receipt,
)

SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
PLAN = HYPE_PROSPECTIVE_VALIDATION_V1
STATE_ID = "12345"
STATE_DIGEST = "a" * 64


def _campaign_id() -> str:
    return ProspectiveCampaignManifest(
        candidate_spec_id=SPEC.spec_id,
        candidate_id=SPEC.candidate_id,
        validation_not_before_ms=SPEC.validation_not_before_ms,
    ).campaign_id


def _blocks() -> tuple[BlindBlockHealth, ...]:
    return (
        BlindBlockHealth(
            block_index=1,
            settled_trade_count=0,
            remaining_expected_anchors=269,
            maximum_possible_settled_trades=269,
            required_settled_trades=PLAN.min_block_trades,
            recoverable=True,
        ),
        *tuple(
            BlindBlockHealth(
                block_index=index,
                settled_trade_count=0,
                remaining_expected_anchors=270,
                maximum_possible_settled_trades=270,
                required_settled_trades=PLAN.min_block_trades,
                recoverable=True,
            )
            for index in range(2, 5)
        ),
    )


def _monitor(
    *,
    observed: int = 1,
    missed: int = 0,
    health: str = "healthy",
    lineage: str = "append_only_valid",
) -> ProspectiveBlindMonitor:
    return ProspectiveBlindMonitor(
        as_of_ms=PLAN.first_expected_anchor_ms + 5 * 60_000,
        campaign_health_status=health,
        lineage_status=lineage,
        campaign_id=_campaign_id(),
        state_artifact_id=STATE_ID,
        current_state_digest=STATE_DIGEST,
        health_id="b" * 64,
        lineage_receipt_id="c" * 64,
        expected_anchor_count=PLAN.expected_anchor_count,
        expected_anchor_count_to_date=1,
        observation_count_to_date=observed,
        capture_coverage_to_date=str(Decimal(observed)),
        missed_anchor_count_to_date=missed,
        missed_anchor_budget=108,
        remaining_missed_anchor_budget=108 - missed,
        remaining_expected_anchors=PLAN.expected_anchor_count - 1,
        required_final_observation_count=972,
        settled_trade_count=0,
        required_settled_trades=PLAN.min_settled_trades,
        maximum_possible_settled_trades=PLAN.expected_anchor_count - missed,
        overdue_unsettled_count=0,
        block_recoverability=_blocks(),
        irrecoverable_reasons=(),
    )


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _patch_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    observation_anchors: tuple[int, ...],
) -> None:
    monkeypatch.setattr(
        cutover_module,
        "verify_prospective_hype_state_readiness",
        lambda *args, **kwargs: SimpleNamespace(
            readiness_status="post_cutover_state_valid",
            campaign_id=_campaign_id(),
            state_digest=STATE_DIGEST,
            observation_count=len(observation_anchors),
        ),
    )

    class FakeStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def iter_observations(self) -> tuple[SimpleNamespace, ...]:
            return tuple(
                SimpleNamespace(anchor_end_ms=anchor)
                for anchor in observation_anchors
            )

    monkeypatch.setattr(
        cutover_module,
        "ProspectiveEvidenceStore",
        FakeStore,
    )


def test_cutover_acceptance_binds_first_captured_anchor_and_round_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_path = tmp_path / "monitor.json"
    receipt_path = tmp_path / "cutover.json"
    monitor = _monitor()
    _write(monitor_path, monitor.to_dict())
    _patch_state(
        monkeypatch,
        observation_anchors=(PLAN.first_expected_anchor_ms,),
    )
    state_time = PLAN.first_expected_anchor_ms + 10 * 60_000
    audit_time = state_time + 60_000

    receipt = build_prospective_hype_cutover_acceptance(
        monitor_path,
        tmp_path / "state",
        state_artifact_id=STATE_ID,
        state_audited_at_ms=state_time,
        audited_at_ms=audit_time,
    )
    _write(receipt_path, receipt.to_dict())

    verified = verify_prospective_hype_cutover_receipt(receipt_path)

    assert verified == receipt
    assert receipt.cutover_status == "cutover_integrity_valid"
    assert receipt.first_anchor_status == "captured"
    assert receipt.earliest_observation_anchor_ms == PLAN.first_expected_anchor_ms
    assert receipt.pre_cutover_observation_count == 0
    assert receipt.observation_grid_valid is True
    assert receipt.interim_economics_redacted is True
    payload = receipt.to_dict()
    assert "net_return" not in payload
    assert "mean_net_return" not in payload
    assert len(receipt.receipt_id) == 64


def test_cutover_acceptance_allows_honest_first_anchor_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_path = tmp_path / "monitor.json"
    _write(
        monitor_path,
        _monitor(observed=0, missed=1, health="degraded").to_dict(),
    )
    _patch_state(monkeypatch, observation_anchors=())
    state_time = PLAN.first_expected_anchor_ms + 10 * 60_000

    receipt = build_prospective_hype_cutover_acceptance(
        monitor_path,
        tmp_path / "state",
        state_artifact_id=STATE_ID,
        state_audited_at_ms=state_time,
        audited_at_ms=state_time + 60_000,
    )

    assert receipt.first_anchor_status == "missed"
    assert receipt.observation_count_to_date == 0
    assert receipt.missed_anchor_count_to_date == 1
    assert receipt.earliest_observation_anchor_ms is None


def test_cutover_acceptance_rejects_off_grid_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_path = tmp_path / "monitor.json"
    _write(monitor_path, _monitor().to_dict())
    _patch_state(
        monkeypatch,
        observation_anchors=(PLAN.first_expected_anchor_ms + 30 * 60_000,),
    )
    state_time = PLAN.first_expected_anchor_ms + 10 * 60_000

    with pytest.raises(
        ProspectiveCutoverAcceptanceError,
        match="OBSERVATION_ANCHOR_GRID_INVALID",
    ):
        build_prospective_hype_cutover_acceptance(
            monitor_path,
            tmp_path / "state",
            state_artifact_id=STATE_ID,
            state_audited_at_ms=state_time,
            audited_at_ms=state_time + 60_000,
        )


def test_cutover_acceptance_waits_for_append_only_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_path = tmp_path / "monitor.json"
    _write(
        monitor_path,
        _monitor(lineage="waiting_for_second_frozen_format_state").to_dict(),
    )
    _patch_state(
        monkeypatch,
        observation_anchors=(PLAN.first_expected_anchor_ms,),
    )
    state_time = PLAN.first_expected_anchor_ms + 10 * 60_000

    with pytest.raises(
        ProspectiveCutoverAcceptanceError,
        match="CUTOVER_LINEAGE_NOT_READY",
    ):
        build_prospective_hype_cutover_acceptance(
            monitor_path,
            tmp_path / "state",
            state_artifact_id=STATE_ID,
            state_audited_at_ms=state_time,
            audited_at_ms=state_time + 60_000,
        )


def test_tampered_cutover_receipt_fails_identity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_path = tmp_path / "monitor.json"
    receipt_path = tmp_path / "cutover.json"
    _write(monitor_path, _monitor().to_dict())
    _patch_state(
        monkeypatch,
        observation_anchors=(PLAN.first_expected_anchor_ms,),
    )
    state_time = PLAN.first_expected_anchor_ms + 10 * 60_000
    receipt = build_prospective_hype_cutover_acceptance(
        monitor_path,
        tmp_path / "state",
        state_artifact_id=STATE_ID,
        state_audited_at_ms=state_time,
        audited_at_ms=state_time + 60_000,
    ).to_dict()
    receipt["first_anchor_status"] = "missed"
    _write(receipt_path, receipt)

    with pytest.raises(
        ProspectiveCutoverAcceptanceError,
        match="CUTOVER_RECEIPT_ID_MISMATCH",
    ):
        verify_prospective_hype_cutover_receipt(receipt_path)
