"""No repaired v1 economics may enter fresh precommitted v2 paired paper."""

from __future__ import annotations

import asyncio
import json
from typing import cast
from pathlib import Path

import pytest

from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    both_side_trend_matched_shadow_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FORWARD_NOT_BEFORE_MS_V2,
    FROZEN_AT_MS_V2,
    PRECOMMITMENT_V2,
    TRIAL_ID_V2,
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.loss_context_paired_shadow_runtime import (
    LossContextPairedShadowRuntime,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    PairedShadowTrendSidecar,
    TREND_PAIR_STATE_ROOT,
    TREND_V2_FREEZE_FILE,
    TREND_V2_STATE_ROOT,
    TREND_V2_SUMMARY_FILE,
    prepare_trend_pair_freeze,
    start_trend_paired_shadow_sidecar,
)


def test_v2_is_a_new_fixed_identical_hypothesis_not_a_v1_restart() -> None:
    v1 = both_side_trend_matched_shadow_freeze()
    v2 = both_side_trend_matched_shadow_v2_freeze()
    assert v2.candidate_id != v1.candidate_id
    assert v2.loss_context_candidate_id != v1.loss_context_candidate_id
    assert v2.source_composition_digest != v1.source_composition_digest
    assert (v2.dimensions, v2.values) == (("lead_strategy",), ("trend",))
    assert v2.source_paper_run_id == v1.source_paper_run_id
    assert v2.source_paper_head_sha == v1.source_paper_head_sha
    assert v2.frozen_at_ms == FROZEN_AT_MS_V2
    assert v2.prospective_not_before_ms == FORWARD_NOT_BEFORE_MS_V2
    assert FORWARD_NOT_BEFORE_MS_V2 - FROZEN_AT_MS_V2 == 6 * 3600 * 1000
    assert PRECOMMITMENT_V2["minimum_forward_duration_ms"] == 72 * 3600 * 1000
    assert PRECOMMITMENT_V2["candidate"] == (
        "block_lead_strategy_trend_on_both_long_and_short"
    )
    assert PRECOMMITMENT_V2["unsigned_account_advances_allowed"] is False
    assert PRECOMMITMENT_V2["open_source_gaps_allowed_for_certification"] is False
    assert PRECOMMITMENT_V2["previous_v1_outcome_admissible"] is False
    assert TRIAL_ID_V2.endswith("capital-matched-shadow-v2")
    assert v2.paper_only and v2.research_only
    assert not v2.promotion_authority and not v2.execution_authority


def test_v2_precommit_creates_only_new_freeze_and_preserves_v1_bytes(
    tmp_path: Path,
) -> None:
    v1_root = tmp_path / TREND_PAIR_STATE_ROOT
    v1_root.mkdir()
    original = b"IMMUTABLE_FAILED_V1_ACCOUNT_BYTES"
    (v1_root / "baseline-execution.sqlite3").write_bytes(original)
    path = prepare_trend_pair_freeze(
        tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
        campaign="v2",
    )
    assert path.name == TREND_V2_FREEZE_FILE
    assert not (tmp_path / TREND_V2_STATE_ROOT).exists()
    assert (v1_root / "baseline-execution.sqlite3").read_bytes() == original
    assert not (tmp_path / "both-side-trend-paired-shadow-freeze.json").exists()
    assert verify_loss_context_portfolio_shadow_freeze(path) == (
        both_side_trend_matched_shadow_v2_freeze()
    )
    sealed = path.read_bytes()
    assert prepare_trend_pair_freeze(
        tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
        campaign="v2",
    ).read_bytes() == sealed
    altered = json.loads(path.read_text())
    altered["candidate_id"] = "0" * 64
    path.write_text(json.dumps(altered))
    with pytest.raises((ValueError, RuntimeError)):
        prepare_trend_pair_freeze(
            tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
            campaign="v2",
        )
    assert (v1_root / "baseline-execution.sqlite3").read_bytes() == original


def test_v2_rejects_unfrozen_legacy_account_adoption(tmp_path: Path) -> None:
    root = tmp_path / TREND_V2_STATE_ROOT
    root.mkdir()
    (root / "candidate-execution.sqlite3").write_bytes(b"untrusted")
    with pytest.raises(RuntimeError, match="without its freeze"):
        prepare_trend_pair_freeze(
            tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
            campaign="v2",
        )
    assert not (tmp_path / TREND_V2_FREEZE_FILE).exists()


def test_v2_rejects_unknown_campaign_and_state_root_alias(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown"):
        prepare_trend_pair_freeze(
            tmp_path, legacy_shadow_root_name="old", campaign="v3",
        )
    with pytest.raises(ValueError, match="must not reuse"):
        prepare_trend_pair_freeze(
            tmp_path, legacy_shadow_root_name=TREND_V2_STATE_ROOT,
            campaign="v2",
        )


def test_pre_freeze_attempt_does_not_create_accounts_or_freeze(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="before its immutable freeze"):
        start_trend_paired_shadow_sidecar(
            None,
            paper_root=tmp_path,
            replay_config=None,  # rejected prior to actor creation
            selected_markets=(),
            startup_timestamp_ms=FROZEN_AT_MS_V2 - 1,
            legacy_shadow_root_name="loss-context-paired-v5",
            campaign="v2",
        )
    assert list(tmp_path.iterdir()) == []


def test_v2_artifact_publishes_separately_before_big_resumes() -> None:
    source = Path(".github/workflows/continuous-paper.yml").read_text()
    v2_verify = source.index(
        "      - name: Verify fresh v2 trend paired account consistency before source ZIP"
    )
    v2_upload = source.index(
        "      - name: Upload isolated fresh v2 trend paired-paper evidence"
    )
    resume = source.index("      - name: Pack fast continuous paper resume state")
    v1_upload = source.index(
        "      - name: Upload isolated both-side trend paired-paper evidence"
    )
    assert v1_upload < v2_verify < v2_upload < resume
    assert "trend-paired-v2-terminal-consistency.json" in source
    assert "continuous-paper-both-side-trend-paired-shadow-v2-" in source
    assert TREND_V2_FREEZE_FILE in source
    assert TREND_V2_SUMMARY_FILE in source
    assert TREND_V2_STATE_ROOT in source
    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "Queue exact successor from fast resume" in source


def test_legacy_v1_source_verification_is_still_separate() -> None:
    paper = Path("src/cocomelon/continuous_paper.py").read_text()
    assert "started_at_ms >= FROZEN_AT_MS_V2" in paper
    assert "campaign=trend_campaign" in paper
    assert "TREND_V2_SUMMARY_FILE" in paper
    assert "TREND_PAIR_SUMMARY_FILE" in paper
    assert "TRIAL_ID_V2" in paper


class _FrozenV2ReceiptActor:
    candidate_id = both_side_trend_matched_shadow_v2_freeze().candidate_id

    def status_payload(self) -> dict[str, object]:
        return {"failed": False, "candidate_id": self.candidate_id}

    async def checkpoint(self, *, end_ms: int) -> dict[str, object]:
        return {"marker": "pure paper", "end_ms": end_ms}

    def fail_closed(self, reason: str) -> None:
        raise AssertionError(reason)


@pytest.mark.parametrize(
    "startup,after_freeze,after_embargo",
    [
        (FROZEN_AT_MS_V2, True, False),
        (FROZEN_AT_MS_V2 + 60_000, True, False),
        (FORWARD_NOT_BEFORE_MS_V2 - 1, True, False),
        (FORWARD_NOT_BEFORE_MS_V2, True, True),
        (FORWARD_NOT_BEFORE_MS_V2 + 1, True, True),
    ],
)
def test_fresh_v2_receipt_distinguishes_freeze_from_six_hour_entry_embargo(
    tmp_path: Path, startup: int, after_freeze: bool, after_embargo: bool,
) -> None:
    actor = cast(LossContextPairedShadowRuntime, _FrozenV2ReceiptActor())
    sidecar = PairedShadowTrendSidecar(
        None, actor,
        summary_path=tmp_path / TREND_V2_SUMMARY_FILE,
        startup_timestamp_ms=startup,
        campaign="v2",
    )
    asyncio.run(sidecar._checkpoint_trend(end_ms=startup + 1))
    receipt = json.loads((tmp_path / TREND_V2_SUMMARY_FILE).read_text())
    assert receipt["started_after_frozen_boundary"] is after_freeze
    assert receipt["started_after_forward_entry_embargo"] is after_embargo
    assert receipt["frozen_forward_not_before_ms"] == FORWARD_NOT_BEFORE_MS_V2
    assert receipt["checkpoint_published"] is True
    assert receipt["execution_authority"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["forward_profitable_signed_account_edge_proven"] is False
