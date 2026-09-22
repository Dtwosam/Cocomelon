from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    HistoricalDiscoveryFreezeSpec,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
    ProspectiveValidationPlan,
)

RUNTIME_ATTESTATION_SCHEMA_VERSION = 1


class ProspectiveRuntimeAttestationError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _require_git_sha(value: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("observer_source_revision must be a lowercase 40-character git SHA")


@dataclass(frozen=True, slots=True)
class ProspectiveRuntimeAttestation:
    candidate_spec_id: str
    validation_plan_id: str
    observer_source_revision: str
    schema_version: int = RUNTIME_ATTESTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.candidate_spec_id, "candidate_spec_id")
        _require_sha256(self.validation_plan_id, "validation_plan_id")
        _require_git_sha(self.observer_source_revision)
        if self.schema_version != RUNTIME_ATTESTATION_SCHEMA_VERSION:
            raise ValueError("unsupported prospective runtime attestation schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_spec_id": self.candidate_spec_id,
            "validation_plan_id": self.validation_plan_id,
            "observer_source_revision": self.observer_source_revision,
            "schema_version": self.schema_version,
        }

    @property
    def attestation_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "attestation_id": self.attestation_id,
        }


def ensure_prospective_runtime_attestation(
    root: str | Path,
    *,
    observer_source_revision: str,
    as_of_ms: int,
    spec: HistoricalDiscoveryFreezeSpec = (
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    ),
    plan: ProspectiveValidationPlan = HYPE_PROSPECTIVE_VALIDATION_V1,
) -> ProspectiveRuntimeAttestation:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if plan.candidate_spec_id != spec.spec_id:
        raise ProspectiveRuntimeAttestationError(
            "prospective validation plan does not match frozen candidate"
        )

    expected = ProspectiveRuntimeAttestation(
        candidate_spec_id=spec.spec_id,
        validation_plan_id=plan.plan_id,
        observer_source_revision=observer_source_revision,
    )
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    path = root_path / "runtime.json"
    encoded = (_canonical_json(expected.to_dict()) + "\n").encode("utf-8")

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProspectiveRuntimeAttestationError(
                "invalid prospective runtime attestation"
            ) from exc
        if not isinstance(raw, dict):
            raise ProspectiveRuntimeAttestationError(
                "prospective runtime attestation must be an object"
            )
        try:
            existing = ProspectiveRuntimeAttestation(
                candidate_spec_id=str(raw["candidate_spec_id"]),
                validation_plan_id=str(raw["validation_plan_id"]),
                observer_source_revision=str(raw["observer_source_revision"]),
                schema_version=int(raw["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveRuntimeAttestationError(
                "invalid prospective runtime attestation payload"
            ) from exc
        if raw.get("attestation_id") != existing.attestation_id:
            raise ProspectiveRuntimeAttestationError(
                "prospective runtime attestation identity mismatch"
            )
        if existing != expected:
            raise ProspectiveRuntimeAttestationError(
                "conflicting prospective runtime attestation"
            )
        if path.read_bytes() != encoded:
            raise ProspectiveRuntimeAttestationError(
                "non-canonical prospective runtime attestation"
            )
        return existing

    if as_of_ms >= spec.validation_not_before_ms:
        raise ProspectiveRuntimeAttestationError(
            "POST_CUTOVER_RUNTIME_ATTESTATION_REQUIRED"
        )

    temporary = path.with_name("runtime.json.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

    return expected
