from __future__ import annotations

import json

import pytest

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import ProspectiveEvidenceStore
from cocomelon.research.prospective_state_continuity import (
    ProspectiveStateContinuityError,
    ProspectiveStateContinuityStatus,
    verify_prospective_state_continuity,
)

SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1


def test_pre_cutover_empty_state_allows_bootstrap(tmp_path) -> None:
    result = verify_prospective_state_continuity(
        tmp_path,
        restored_artifact_id="none",
        as_of_ms=SPEC.validation_not_before_ms - 1,
    )

    assert result.status is ProspectiveStateContinuityStatus.PRE_CUTOVER_BOOTSTRAP
    assert result.restored_artifact_id is None
    assert result.campaign_id is None
    assert result.prior_state_digest is None
    assert not (tmp_path / "manifest.json").exists()


def test_post_cutover_missing_restore_fails_closed(tmp_path) -> None:
    with pytest.raises(
        ProspectiveStateContinuityError,
        match="POST_CUTOVER_PROSPECTIVE_STATE_RESTORE_REQUIRED",
    ):
        verify_prospective_state_continuity(
            tmp_path,
            restored_artifact_id="none",
            as_of_ms=SPEC.validation_not_before_ms,
        )


def test_restored_campaign_returns_prior_state_digest(tmp_path) -> None:
    store = ProspectiveEvidenceStore(tmp_path, spec=SPEC)

    result = verify_prospective_state_continuity(
        tmp_path,
        restored_artifact_id="123456",
        as_of_ms=SPEC.validation_not_before_ms,
    )

    assert result.status is ProspectiveStateContinuityStatus.RESTORED
    assert result.restored_artifact_id == "123456"
    assert result.campaign_id == store.manifest.campaign_id
    assert result.prior_state_digest == store.state_digest


def test_artifact_id_requires_restored_manifest(tmp_path) -> None:
    with pytest.raises(
        ProspectiveStateContinuityError,
        match="RESTORED_PROSPECTIVE_MANIFEST_MISSING",
    ):
        verify_prospective_state_continuity(
            tmp_path,
            restored_artifact_id="123",
            as_of_ms=SPEC.validation_not_before_ms - 1,
        )


def test_unattributed_pre_cutover_state_fails_closed(tmp_path) -> None:
    ProspectiveEvidenceStore(tmp_path, spec=SPEC)

    with pytest.raises(
        ProspectiveStateContinuityError,
        match="unattributed prospective state",
    ):
        verify_prospective_state_continuity(
            tmp_path,
            restored_artifact_id=None,
            as_of_ms=SPEC.validation_not_before_ms - 1,
        )


def test_wrong_campaign_manifest_fails_through_store_integrity(tmp_path) -> None:
    ProspectiveEvidenceStore(tmp_path, spec=SPEC)
    manifest_path = tmp_path / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["candidate_id"] = "wrong-candidate"
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="conflicting prospective campaign manifest"):
        verify_prospective_state_continuity(
            tmp_path,
            restored_artifact_id="123",
            as_of_ms=SPEC.validation_not_before_ms,
        )


def test_non_numeric_artifact_id_is_rejected(tmp_path) -> None:
    with pytest.raises(
        ProspectiveStateContinuityError,
        match="artifact id must be numeric",
    ):
        verify_prospective_state_continuity(
            tmp_path,
            restored_artifact_id="abc",
            as_of_ms=SPEC.validation_not_before_ms - 1,
        )
