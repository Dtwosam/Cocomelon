from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
    OriginalRankFeatureInputBatchStore,
)
from cocomelon.scanner.ranker import rank_opportunities
from scripts.attest_paper_short_rank_artifact import (
    REQUIRED_SUCCESSFUL_PAPER_STEPS,
)
from scripts.audit_paper_short_rank_coarse_scores import (
    FULL_FEATURE_SUCCESS_STEPS,
    audit_original_worker_rank_score_sources,
)
from scripts.seal_paper_short_rank_archive import (
    ARCHIVE_NAME,
    RECEIPT_NAME as RANK_RECEIPT,
    seal_completed_short_rank_archive,
)
from scripts.seal_paper_short_rank_full_features import (
    BUNDLE_FILE,
    RECEIPT_FILE,
    seal_original_short_rank_full_feature_inputs,
)

RUN = 38173963878
HEAD = "a" * 40
REPO = "Dtwosam/Cocomelon"
OBS = 1_790_000_000_000


def _feature(coin: str, ordinal: int) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", coin),
        as_of_ms=OBS - 10,
        source_received_at_ms=OBS - 20,
        schema_version=1,
        day_return=Decimal(ordinal) / Decimal("100"),
        funding=Decimal(ordinal) / Decimal("10000"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("100000"),
        oi_change_fraction=Decimal(ordinal) / Decimal("1000"),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.MIXED,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("synthetic-unit-not-mainnet",),
    )


def _outer(payload: dict[str, bytes]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_STORED) as z:
        for name, value in payload.items():
            z.writestr(name, value)
    return data.getvalue()


def _inputs(
    tmp_path: Path, *,
    tamper_score: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes, bytes]:
    root = tmp_path / "worker-state"
    features = {
        feature.market.canonical: feature
        for feature in (_feature("BTC", 1), _feature("ETH", 2), _feature("SOL", 3))
    }
    decisions = tuple(
        EligibilityDecision(
            market=feature.market, rankable=True, deep_ready=False, reasons=(),
        )
        for feature in features.values()
    )
    ranks = rank_opportunities(
        tuple(features.values()), decisions, mode="coarse",
    )
    original = FirstSeenRankSnapshot.from_observation(
        observed_at_ms=OBS,
        captured_at_ms=OBS + 50,
        features=features, ranks=ranks,
    )
    if tamper_score:
        first = original.ranks[0]
        original = replace(
            original,
            ranks=(
                (first[0], 1, "0.99999", first[3]),
                *original.ranks[1:],
            ),
        )
    assert FirstSeenRankSnapshotStore(
        root / "prospective-short-rank-first-seen"
    ).append(original)
    input_batch = OriginalRankFeatureInputBatch.from_original_rank(
        original, features,
    )
    assert OriginalRankFeatureInputBatchStore(
        root / "prospective-short-rank-full-feature-inputs"
    ).append(input_batch)
    rank_out = tmp_path / "sealed-rank"
    full_out = tmp_path / "sealed-feature"
    rank_receipt = seal_completed_short_rank_archive(
        root, rank_out, worker_run_id=RUN,
        worker_run_attempt=1, worker_head_sha=HEAD,
        sealed_at_ms=OBS + 5_000,
    )
    full_receipt = seal_original_short_rank_full_feature_inputs(
        root, full_out, worker_run_id=RUN,
        worker_run_attempt=1, worker_head_sha=HEAD,
        sealed_at_ms=OBS + 5_000,
    )
    assert rank_receipt["rank_source_status"] == "locally_sealed"
    assert full_receipt["full_rank_feature_status"] == (
        "locally_sealed_prospective_suffix"
    )
    rank_zip = _outer({
        RANK_RECEIPT: (rank_out / RANK_RECEIPT).read_bytes(),
        ARCHIVE_NAME: (rank_out / ARCHIVE_NAME).read_bytes(),
    })
    feature_zip = _outer({
        RECEIPT_FILE: (full_out / RECEIPT_FILE).read_bytes(),
        BUNDLE_FILE: (full_out / BUNDLE_FILE).read_bytes(),
    })
    run: dict[str, Any] = {
        "id": RUN, "status": "completed", "conclusion": "success",
        "run_attempt": 1, "head_sha": HEAD,
        "event": "workflow_dispatch", "head_branch": "main",
        "path": ".github/workflows/continuous-paper.yml",
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
    }
    jobs: dict[str, Any] = {
        "jobs": [{
            "name": "paper", "status": "completed", "conclusion": "success",
            "run_attempt": 1,
            "steps": [
                {"name": name, "conclusion": "success"}
                for name in (
                    *REQUIRED_SUCCESSFUL_PAPER_STEPS,
                    *FULL_FEATURE_SUCCESS_STEPS,
                )
            ],
        }],
    }
    artifacts: dict[str, Any] = {"artifacts": []}
    for index, (suffix, raw) in enumerate((
        ("", rank_zip), ("-full-inputs", feature_zip),
    )):
        name = (
            f"continuous-paper-first-seen-short-rank{suffix}-{RUN}-1"
        )
        artifacts["artifacts"].append({
            "id": 1000 + index,
            "name": name,
            "expired": False,
            "size_in_bytes": len(raw),
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "workflow_run": {"id": RUN, "head_sha": HEAD},
        })
    return run, jobs, artifacts, rank_zip, feature_zip


def _audit(
    data: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes, bytes],
) -> dict[str, object]:
    run, jobs, art, rank_zip, full_zip = data
    return audit_original_worker_rank_score_sources(
        run_id=RUN, run_attempt=1,
        run_json=run, jobs_json=jobs,
        artifacts_json=art,
        rank_artifact_zip=rank_zip,
        full_input_artifact_zip=full_zip,
        expected_repository=REPO,
    )


def test_fully_verified_original_worker_two_zips_reproduce_coarse_rank_scores(
    tmp_path: Path,
) -> None:
    result = _audit(_inputs(tmp_path))
    assert result["rank_coarse_score_audit_status"] == (
        "github_bound_arithmetic_verified"
    )
    assert result["both_original_worker_artifact_sha256s_verified"] is True
    assert result["original_rank_feature_scores_recomputed"] is True
    assert result["recomputed_original_ranked_markets"] == 3
    assert result["recomputed_complete_rank_batches"] == 1
    assert result["rankable_market_membership_independently_reconstructed"] is False
    assert result["mainnet_market_source_and_gaps_authenticated"] is False
    assert result["signed_account_positive_after_cost_expectancy_proven"] is False
    assert result["ready_for_review"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_self_sealed_original_ordinal_score_falsification_refused_even_with_valid_zips(
    tmp_path: Path,
) -> None:
    result = _audit(_inputs(tmp_path, tamper_score=True))
    assert result["rank_coarse_score_audit_status"] == "unverified"
    assert result["failure_reason_code"] == (
        "original_worker_coarse_score_source_or_arithmetic_invalid"
    )
    assert result["both_original_worker_artifact_sha256s_verified"] is False
    assert result["ready_for_review"] is False


def test_missing_full_inputs_or_failed_original_export_steps_are_not_verified(
    tmp_path: Path,
) -> None:
    data = _inputs(tmp_path)
    run, jobs, artifacts, rank_zip, _full_zip = data
    missing = audit_original_worker_rank_score_sources(
        run_id=RUN, run_attempt=1,
        run_json=run, jobs_json=jobs,
        artifacts_json=artifacts, rank_artifact_zip=rank_zip,
        full_input_artifact_zip=None, expected_repository=REPO,
    )
    assert missing["failure_reason_code"] == (
        "original_full_feature_input_archive_unavailable"
    )
    with_missing_step = {
        "jobs": [{
            **jobs["jobs"][0],
            "steps": [
                step for step in jobs["jobs"][0]["steps"]
                if step["name"] != FULL_FEATURE_SUCCESS_STEPS[0]
            ],
        }],
    }
    report = _audit((
        run, with_missing_step, artifacts, rank_zip, data[4],
    ))
    assert report["failure_reason_code"] == (
        "original_full_input_export_step_not_successful"
    )


def test_unexpected_failed_worker_or_modified_github_digest_fails_closed(
    tmp_path: Path,
) -> None:
    run, jobs, arts, rank, full = _inputs(tmp_path)
    failed = _audit((
        {**run, "conclusion": "failure"},
        jobs, arts, rank, full,
    ))
    assert failed["failure_reason_code"] == "original_worker_rank_source_unverified"
    tampered = _audit((
        run, jobs, arts, rank, full + b"tampered",
    ))
    assert tampered["failure_reason_code"] == (
        "original_worker_coarse_score_source_or_arithmetic_invalid"
    )


def test_expected_upgrade_only_worker_does_not_become_successful_research(
    tmp_path: Path,
) -> None:
    run, jobs, arts, rank, full = _inputs(tmp_path)
    worker = jobs["jobs"][0]
    upgrade = {
        "jobs": [{
            **worker, "conclusion": "failure",
            "steps": [
                *worker["steps"],
                {"name": "Upload durable continuous paper state", "conclusion": "success"},
                {"name": "Fail closed on upgrade handoff source", "conclusion": "failure"},
            ],
        }],
    }
    result = _audit((
        {**run, "conclusion": "failure"},
        upgrade, arts, rank, full,
    ))
    assert result["rank_coarse_score_audit_status"] == (
        "github_bound_upgrade_handoff_arithmetic_only"
    )
    assert result["original_worker_source_class"] == "upgrade_handoff_only"
    assert result["both_original_worker_artifact_sha256s_verified"] is True
    assert result["full_account_trial"] is False
    assert result["ready_for_review"] is False


def test_real_workflow_cli_module_returns_durable_negative_missing_source(
    tmp_path: Path,
) -> None:
    workflow = Path(
        ".github/workflows/original-short-rank-source-audit.yml"
    ).read_text(encoding="utf-8")
    assert "python -m scripts.audit_paper_short_rank_coarse_scores" in workflow
    assert "original-first-seen-short-rank-coarse-score-audit-" in workflow
    assert "full-input-artifact.zip" in workflow
    assert "Authorization: Bearer $GH_TOKEN" in workflow
    assert "actions: read" in workflow
    assert "continuous-paper-trader --" not in workflow

    receipt = tmp_path / "arithmetic-unverified.json"
    result = subprocess.run([
        sys.executable,
        "-m", "scripts.audit_paper_short_rank_coarse_scores",
        "--source-dir", str(tmp_path / "missing"),
        "--source-run-id", str(RUN),
        "--source-run-attempt", "1",
        "--repository", REPO,
        "--output", str(receipt),
    ], capture_output=True, text=True, check=False,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["rank_coarse_score_audit_status"] == "unverified"
    assert payload["failure_reason_code"] == (
        "original_worker_rank_archive_unavailable"
    )
    assert payload["ready_for_review"] is False
    assert json.loads(result.stdout.strip()) == payload
