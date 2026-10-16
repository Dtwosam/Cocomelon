"""The source chain must deny forged links, gaps and contract drift.

No synthetic test of a source-chain *declaration* may become proof of actual
exchange completeness, 72h observed L2, signed accounts or profit.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    SourceSegment,
)
from cocomelon.research.fresh_long_trend_source_chain import (
    OriginalV3SourceChainError,
    OriginalV3WorkerSourceWitness,
    audit_original_v3_worker_source_chain,
)


def _worker(
    number: int, start: int, end: int,
    predecessor: int | None = None, *,
    fee_schedule_id: str = "paper-fees-v1",
) -> OriginalV3WorkerSourceWitness:
    segment = SourceSegment(
        relative_path=(
            f"events/2026-10-16/l2_book/TEST/segment-{number:06d}.jsonl"
        ),
        partition="events/2026-10-16/l2_book/TEST",
        sha256=f"{number:064x}",
        byte_count=100,
        row_count=10,
        schema_version=1,
        first_available_at_ms=start,
        last_available_at_ms=end,
    )
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=start,
        end_ms=end,
        segments=(segment,),
        gap_refs=(),
        code_revision="a" * 40,
        config_digest="f" * 64,
        feature_version="features-v1",
        strategy_version="frozen-long-trend-v3",
        risk_version="original-risk-v1",
        execution_config_version="paper-v1",
        fee_schedule_id=fee_schedule_id,
        replay_engine_version="replay-v1",
        dataset_manifest_id=None,
    )
    return OriginalV3WorkerSourceWitness(
        github_source={
            "run_id": number,
            "run_attempt": 1,
            "run_head_sha": "a" * 40,
            "original_artifact_id": number + 9000000,
            "original_zip_sha256": f"{number + 5000:064x}",
            "manifest_id": manifest.manifest_id,
            "declared_predecessor_run_id": (
                None if predecessor is None else str(predecessor)
            ),
            "declared_predecessor_run_attempt": (
                None if predecessor is None else "1"
            ),
            "original_zip_bytes_match_supplied_github_digest": True,
            "supplied_github_run_job_artifact_identity_crosschecked": True,
            "source_records_not_changed_by_audit": True,
            "original_worker_link_receipt_matches_run": True,
            "signed_cross_worker_handoff_proven": False,
            "net_after_cost_profitability_proven": False,
            "promotion_authority": False,
            "execution_authority": False,
        },
        manifest=manifest,
    )


def _pair() -> tuple[OriginalV3WorkerSourceWitness, ...]:
    return (
        _worker(100, 1000000, 2000000),
        _worker(101, 2020000, 3000000, 100),
        _worker(102, 3050000, 4000000, 101),
    )


def _with(
    witness: OriginalV3WorkerSourceWitness,
    *, origin: dict[str, object] | None = None,
    manifest: ReplayManifest | None = None,
) -> OriginalV3WorkerSourceWitness:
    return OriginalV3WorkerSourceWitness(
        github_source=origin or witness.github_source,
        manifest=manifest or witness.manifest,
    )


def test_contiguous_source_claim_is_only_nonqualifying_negative_preflight() -> None:
    report = audit_original_v3_worker_source_chain(_pair())
    assert report["source_worker_count"] == 3
    assert report["original_manifest_record_rows"] == 30
    assert report["original_chain_first_manifest_timestamp_ms"] == 1000000
    assert report["original_chain_last_manifest_timestamp_ms"] == 4000000
    assert report["original_manifest_nominal_span_ms"] == 3000000
    assert report["maximum_declared_handoff_source_silence_ms"] == 50000
    assert report["declared_worker_chain_local_order_consistent"] is True
    for flag in (
        "independent_predecessor_restore_certified",
        "market_by_market_72h_l2_observation_certified",
        "original_venue_event_completeness_certified",
        "unrecorded_source_gaps_excluded",
        "signed_full_account_continuity_certified",
        "after_cost_absolute_positive_account_edge_verified",
        "profitability_certified",
        "execution_authority",
        "promotion_authority",
    ):
        assert report[flag] is False


def test_72h_nominal_manifest_span_never_certifies_real_l2_or_profit() -> None:
    t0 = 1792130400000
    long = _worker(100, t0, t0 + 72 * 60 * 60 * 1000 + 1)
    report = audit_original_v3_worker_source_chain((long,))
    assert report["original_manifest_nominal_span_ms"] > 72 * 60 * 60 * 1000
    assert report["market_by_market_72h_l2_observation_certified"] is False
    assert report["after_cost_absolute_positive_account_edge_verified"] is False


@pytest.mark.parametrize("change", [
    "wrong_predecessor", "missing_attempt", "self_predecessor",
    "duplicate_artifact", "duplicate_worker", "duplicate_digest",
    "overlap", "gap", "fee_drift", "market_gap", "forged_profit",
    "forged_handoff", "forged_promotion", "source_without_zip",
    "manifest_substitution",
])
def test_broken_or_forged_chain_rejected(
    change: str,
) -> None:
    first, second, third = _pair()
    origin = dict(second.github_source)
    manifest = second.manifest
    if change == "wrong_predecessor":
        origin["declared_predecessor_run_id"] = "777"
    elif change == "missing_attempt":
        origin["declared_predecessor_run_attempt"] = None
    elif change == "self_predecessor":
        origin["declared_predecessor_run_id"] = "101"
    elif change == "duplicate_artifact":
        origin["original_artifact_id"] = first.github_source["original_artifact_id"]
    elif change == "duplicate_worker":
        origin["run_id"] = first.github_source["run_id"]
    elif change == "duplicate_digest":
        origin["original_zip_sha256"] = first.github_source["original_zip_sha256"]
    elif change == "overlap":
        manifest = replace(manifest, start_ms=1900000)
        origin["manifest_id"] = manifest.manifest_id
    elif change == "gap":
        manifest = replace(manifest, start_ms=2700000)
        origin["manifest_id"] = manifest.manifest_id
    elif change == "fee_drift":
        manifest = replace(manifest, fee_schedule_id="different-fees")
        origin["manifest_id"] = manifest.manifest_id
    elif change == "market_gap":
        manifest = replace(manifest, gap_refs=("source-l2-hole",))
        origin["manifest_id"] = manifest.manifest_id
    elif change == "forged_profit":
        origin["net_after_cost_profitability_proven"] = True
    elif change == "forged_handoff":
        origin["signed_cross_worker_handoff_proven"] = True
    elif change == "forged_promotion":
        origin["promotion_authority"] = True
    elif change == "source_without_zip":
        origin["original_zip_bytes_match_supplied_github_digest"] = False
    else:
        origin["manifest_id"] = "0" * 24
    changed = _with(second, origin=origin, manifest=manifest)
    with pytest.raises(OriginalV3SourceChainError):
        audit_original_v3_worker_source_chain((first, changed, third))


def test_external_predecessor_for_first_worker_is_not_falsely_certified() -> None:
    first, second, third = _pair()
    modified = dict(first.github_source)
    modified["declared_predecessor_run_id"] = "99"
    modified["declared_predecessor_run_attempt"] = "1"
    chain = audit_original_v3_worker_source_chain((
        _with(first, origin=modified), second, third,
    ))
    assert chain["original_chain_first_unverified_predecessor_run_id"] == "99"
    assert chain["independent_predecessor_restore_certified"] is False


def test_empty_witness_set_must_not_qualify() -> None:
    with pytest.raises(OriginalV3SourceChainError):
        audit_original_v3_worker_source_chain(())
