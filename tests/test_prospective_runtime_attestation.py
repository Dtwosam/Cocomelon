from __future__ import annotations

import json

import pytest

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_runtime_attestation import (
    ProspectiveRuntimeAttestationError,
    ensure_prospective_runtime_attestation,
)

SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
PLAN = HYPE_PROSPECTIVE_VALIDATION_V1
REVISION = "a" * 40


def test_pre_cutover_runtime_attestation_is_created_atomically(tmp_path) -> None:
    attestation = ensure_prospective_runtime_attestation(
        tmp_path,
        observer_source_revision=REVISION,
        as_of_ms=SPEC.validation_not_before_ms - 1,
    )

    assert attestation.candidate_spec_id == SPEC.spec_id
    assert attestation.validation_plan_id == PLAN.plan_id
    assert attestation.observer_source_revision == REVISION
    assert len(attestation.attestation_id) == 64
    path = tmp_path / "runtime.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["attestation_id"] == attestation.attestation_id


def test_exact_runtime_attestation_is_idempotent(tmp_path) -> None:
    first = ensure_prospective_runtime_attestation(
        tmp_path,
        observer_source_revision=REVISION,
        as_of_ms=SPEC.validation_not_before_ms - 1,
    )
    second = ensure_prospective_runtime_attestation(
        tmp_path,
        observer_source_revision=REVISION,
        as_of_ms=SPEC.validation_not_before_ms,
    )

    assert first == second


def test_conflicting_source_revision_fails_closed(tmp_path) -> None:
    ensure_prospective_runtime_attestation(
        tmp_path,
        observer_source_revision=REVISION,
        as_of_ms=SPEC.validation_not_before_ms - 1,
    )

    with pytest.raises(
        ProspectiveRuntimeAttestationError,
        match="conflicting prospective runtime attestation",
    ):
        ensure_prospective_runtime_attestation(
            tmp_path,
            observer_source_revision="b" * 40,
            as_of_ms=SPEC.validation_not_before_ms - 1,
        )


def test_missing_runtime_attestation_after_cutover_fails_closed(tmp_path) -> None:
    with pytest.raises(
        ProspectiveRuntimeAttestationError,
        match="POST_CUTOVER_RUNTIME_ATTESTATION_REQUIRED",
    ):
        ensure_prospective_runtime_attestation(
            tmp_path,
            observer_source_revision=REVISION,
            as_of_ms=SPEC.validation_not_before_ms,
        )


def test_malformed_runtime_attestation_fails_closed(tmp_path) -> None:
    (tmp_path / "runtime.json").write_text("{bad json", encoding="utf-8")

    with pytest.raises(
        ProspectiveRuntimeAttestationError,
        match="invalid prospective runtime attestation",
    ):
        ensure_prospective_runtime_attestation(
            tmp_path,
            observer_source_revision=REVISION,
            as_of_ms=SPEC.validation_not_before_ms - 1,
        )


def test_runtime_source_revision_must_be_full_git_sha(tmp_path) -> None:
    with pytest.raises(ValueError, match="40-character git SHA"):
        ensure_prospective_runtime_attestation(
            tmp_path,
            observer_source_revision="short",
            as_of_ms=SPEC.validation_not_before_ms - 1,
        )
