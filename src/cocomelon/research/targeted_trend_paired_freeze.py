from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Final

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.prospective_trend_outside_top10 import (
    ProspectiveTrendOutsideTop10State,
)

# D-087 source: immutable continuous-paper loss-streak audit ZIP from
# completed paper run 37842273469 attempt 1. Original raw member digest,
# not a digest of current/future evaluations. Historic legacy feature
# coverage was incomplete (7 of 134), so this is research discovery only.
SOURCE_RUN_ID: Final = 37842273469
SOURCE_RUN_ATTEMPT: Final = 1
SOURCE_HEAD_SHA: Final = (
    "3bd5bc2c0c389a78aea874e48c0a2bd675f4772e"
)
SOURCE_AUDIT_RAW_SHA256: Final = (
    "bae3928edcf08f303ed63c75c98c4d35731077978e941517a7746531e5899a1b"
)
SOURCE_LAST_CLOSED_AT_MS: Final = 1791489218467
SOURCE_UNRESOLVED_LEGACY_FEATURES: Final = 7
SOURCE_CANDIDATES_CONSIDERED: Final = 18
SOURCE_STABLE_CANDIDATES: Final = 1

DIMENSIONS: Final = ("lead_strategy", "rank_band")
VALUES: Final = ("trend", "outside10")
# No exit horizon is selected or traded. This singleton is carried only
# for compatibility with the pre-existing frozen paired-account schema.
SCHEMA_COMPATIBILITY_HORIZONS_MS: Final = (300_000,)


class TargetedTrendPairedFreezeError(RuntimeError):
    pass


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _source_witness(
    state: ProspectiveTrendOutsideTop10State,
) -> dict[str, object]:
    return {
        "source_kind": (
            "retrospective_loss_streak_context_audit_incomplete_legacy_"
            "attribution"
        ),
        "source_run_id": SOURCE_RUN_ID,
        "source_run_attempt": SOURCE_RUN_ATTEMPT,
        "source_head_sha": SOURCE_HEAD_SHA,
        "source_audit_raw_sha256": SOURCE_AUDIT_RAW_SHA256,
        "source_last_closed_at_ms": SOURCE_LAST_CLOSED_AT_MS,
        "unresolved_legacy_feature_count": SOURCE_UNRESOLVED_LEGACY_FEATURES,
        "explored_context_patterns": SOURCE_CANDIDATES_CONSIDERED,
        "stable_context_patterns": SOURCE_STABLE_CANDIDATES,
        "frozen_entry_hypothesis": state.payload(),
        "tested_dimensions": DIMENSIONS,
        "tested_values": VALUES,
        "no_legacy_composition_gate_credit": True,
        "prospective_portfolio_trial_only": True,
    }


def targeted_trend_paired_freeze(
    state: ProspectiveTrendOutsideTop10State,
) -> LossContextPortfolioShadowFreeze:
    """Re-use the exact account reflow simulator, not its historical gate.

    This independent trial cannot certify the incomplete legacy cohort or
    grant the pre-existing composition freeze any readiness. Portfolio
    benefits are measured only from subsequently matched live-paper stream.
    """
    if state.frozen_at_ms < SOURCE_LAST_CLOSED_AT_MS:
        raise TargetedTrendPairedFreezeError(
            "targeted account trial freeze predates discovery audit"
        )
    if state.started_at_ms != (
        state.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
    ):
        raise TargetedTrendPairedFreezeError(
            "targeted trial forward embargo does not match frozen entry rule"
        )
    witness = _source_witness(state)
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id=_sha256_json(witness),
        source_composition_digest=_sha256_json({
            "source_audit_raw_sha256": SOURCE_AUDIT_RAW_SHA256,
            "historical_candidate_composition_ready": False,
            "historical_feature_coverage_complete": False,
            "source_warning": (
                "This field is a fixed discovery-source witness, "
                "NOT evidence of a legacy portfolio composition pass"
            ),
            "witness": witness,
        }),
        source_max_timestamp_ms=SOURCE_LAST_CLOSED_AT_MS,
        source_paper_run_id=SOURCE_RUN_ID,
        source_paper_run_attempt=SOURCE_RUN_ATTEMPT,
        source_paper_head_sha=SOURCE_HEAD_SHA,
        dimensions=DIMENSIONS,
        values=VALUES,
        horizons_ms=SCHEMA_COMPATIBILITY_HORIZONS_MS,
        frozen_at_ms=state.frozen_at_ms,
        prospective_not_before_ms=state.started_at_ms,
    )


def activate_targeted_trend_paired_freeze(
    path: Path,
    state: ProspectiveTrendOutsideTop10State,
    *,
    paired_state_path: Path,
) -> tuple[LossContextPortfolioShadowFreeze, bool]:
    """Write-once trial: preserve any independently trusted existing freeze.

    Never overwrite original generic compositions, resurrect incomplete
    paired account stores, or backdate the D-087 clean prospective boundary.
    """
    if path.exists():
        return verify_loss_context_portfolio_shadow_freeze(path), False
    if paired_state_path.exists():
        raise TargetedTrendPairedFreezeError(
            "paired account state exists without its original frozen identity"
        )
    freeze = targeted_trend_paired_freeze(state)
    payload = json.dumps(
        freeze.to_dict(),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return verify_loss_context_portfolio_shadow_freeze(path), True
