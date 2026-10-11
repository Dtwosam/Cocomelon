from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from cocomelon.research.prospective_short_rank_full_feature_artifact import (
    ExpectedGithubRankInputArtifact,
    OriginalRankFeatureArtifactError,
    verify_github_original_rank_full_input_artifact,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
    OriginalRankFeatureInputBatchStore,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    ExpectedGithubRankArtifact,
    VerifiedGithubShortRankEvidence,
    verify_github_original_short_rank_artifact,
)
from scripts.seal_paper_short_rank_archive import ARCHIVE_NAME as RANK_ARCHIVE
from scripts.seal_paper_short_rank_archive import RECEIPT_NAME as RANK_RECEIPT
from scripts.seal_paper_short_rank_archive import seal_completed_short_rank_archive
from scripts.seal_paper_short_rank_full_features import (
    BUNDLE_FILE,
    RECEIPT_FILE,
    seal_original_short_rank_full_feature_inputs,
)

HEAD = "a" * 40
RUN = 38166151613
OBS = 1_790_000_000_000
SEAL = OBS + 300_000


def _feature(market: str, at: int) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=at,
        source_received_at_ms=at - 100,
        schema_version=1,
        day_return=None,
        funding=Decimal("0.001"),
        open_interest=Decimal("45000"),
        day_notional_volume=Decimal("2300000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=Decimal("3"),
        bid_depth_25bps=Decimal("10000"),
        ask_depth_25bps=Decimal("11000"),
        book_imbalance=Decimal("0.05"),
        book_age_ms=50,
        trend_regime=TrendRegime.MIXED,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("fixture-original",),
    )


def _outer(contents: dict[str, bytes]) -> bytes:
    dest = io.BytesIO()
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    return dest.getvalue()


def _fixture(
    root: Path, *, legacy: bool = True,
) -> tuple[
    bytes, ExpectedGithubRankArtifact,
    bytes, ExpectedGithubRankInputArtifact,
]:
    state = root / "original"
    rank_store = FirstSeenRankSnapshotStore(
        state / "prospective-short-rank-first-seen"
    )
    input_store = OriginalRankFeatureInputBatchStore(
        state / "prospective-short-rank-full-feature-inputs"
    )
    for ix, market in enumerate(("BTC", "ETH", "SOL")):
        observed = OBS + ix * 30_000
        features = {market: _feature(market, observed)}
        rank = FirstSeenRankSnapshot.from_observation(
            observed_at_ms=observed,
            captured_at_ms=observed + 40,
            features=features,
            ranks=(),
        )
        assert rank_store.append(rank)
        if ix > 0 or not legacy:
            input_store.append(OriginalRankFeatureInputBatch.from_original_rank(
                rank, features,
            ))
    rank_out = root / "rank-output"
    feature_out = root / "feature-output"
    rank_seal = seal_completed_short_rank_archive(
        state, rank_out, worker_run_id=RUN, worker_run_attempt=1,
        worker_head_sha=HEAD, sealed_at_ms=SEAL,
    )
    input_seal = seal_original_short_rank_full_feature_inputs(
        state, feature_out, worker_run_id=RUN, worker_run_attempt=1,
        worker_head_sha=HEAD, sealed_at_ms=SEAL,
    )
    assert rank_seal["rank_source_status"] == "locally_sealed"
    assert input_seal["full_rank_feature_status"] == (
        "locally_sealed_prospective_suffix"
    )
    ranks = _outer({
        RANK_RECEIPT: (rank_out / RANK_RECEIPT).read_bytes(),
        RANK_ARCHIVE: (rank_out / RANK_ARCHIVE).read_bytes(),
    })
    feats = _outer({
        RECEIPT_FILE: (feature_out / RECEIPT_FILE).read_bytes(),
        BUNDLE_FILE: (feature_out / BUNDLE_FILE).read_bytes(),
    })
    rank_expected = ExpectedGithubRankArtifact(
        run_id=RUN, run_attempt=1, head_sha=HEAD,
        artifact_run_id=RUN, artifact_head_sha=HEAD,
        artifact_name=f"continuous-paper-first-seen-short-rank-{RUN}-1",
        artifact_digest=f"sha256:{hashlib.sha256(ranks).hexdigest()}",
        artifact_size_bytes=len(ranks),
    )
    input_expected = ExpectedGithubRankInputArtifact(
        run_id=RUN, run_attempt=1, head_sha=HEAD,
        artifact_run_id=RUN, artifact_head_sha=HEAD,
        artifact_name=(
            f"continuous-paper-first-seen-short-rank-full-inputs-{RUN}-1"
        ),
        artifact_digest=f"sha256:{hashlib.sha256(feats).hexdigest()}",
        artifact_size_bytes=len(feats),
    )
    return ranks, rank_expected, feats, input_expected


def _verify_rank(
    original: bytes, expected: ExpectedGithubRankArtifact,
) -> VerifiedGithubShortRankEvidence:
    return verify_github_original_short_rank_artifact(
        original, expected=expected,
    )


def _rebuilt(
    data: bytes, key: str, changed: bytes,
) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files[key] = changed
    return _outer(files)


def _new_binding(
    data: bytes, source: ExpectedGithubRankInputArtifact,
) -> ExpectedGithubRankInputArtifact:
    return replace(
        source,
        artifact_size_bytes=len(data),
        artifact_digest=f"sha256:{hashlib.sha256(data).hexdigest()}",
    )


def test_true_original_full_rank_input_suffix_integrity_and_legacy_gap(
    tmp_path: Path,
) -> None:
    rank_zip, rank_api, feature_zip, feature_api = _fixture(tmp_path)
    original = _verify_rank(rank_zip, rank_api)
    checked = verify_github_original_rank_full_input_artifact(
        feature_zip, expected=feature_api, original_rank=original,
    )
    receipt = checked.receipt()
    assert receipt["verified_full_input_batches"] == 2
    assert receipt["historical_rank_snapshots_without_full_inputs"] == 1
    assert receipt["rank_feature_payload_identity_closed_for_verified_suffix"] is True
    assert receipt["entire_rank_history_full_inputs_present"] is False
    assert receipt["github_artifact_sha256_and_inner_zip_verified"] is True
    assert receipt["full_hyperliquid_market_stream_attested"] is False
    assert receipt["full_account_trial"] is False
    assert receipt["ready_for_review"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["execution_authority"] is False
    assert checked.batches[0].features[0].market.canonical == "ETH"
    assert checked.batches[1].features[0].market.canonical == "SOL"


def test_zero_legacy_input_uncovered_is_not_market_provenance(
    tmp_path: Path,
) -> None:
    rank_zip, rank_api, feat_zip, feat_api = _fixture(
        tmp_path, legacy=False,
    )
    verified = verify_github_original_rank_full_input_artifact(
        feat_zip, expected=feat_api,
        original_rank=_verify_rank(rank_zip, rank_api),
    )
    assert verified.historical_rank_snapshots_without_inputs == 0
    assert verified.receipt()["entire_rank_history_full_inputs_present"] is True
    assert verified.receipt()["full_hyperliquid_market_stream_attested"] is False
    assert verified.receipt()["all_market_data_gaps_resolved"] is False
    assert verified.receipt()["ready_for_review"] is False


def test_changed_github_outer_artifact_bytes_fail_before_feature_read(
    tmp_path: Path,
) -> None:
    rank_zip, rank_api, feat_zip, feat_api = _fixture(tmp_path)
    with pytest.raises(OriginalRankFeatureArtifactError, match="SHA256"):
        verify_github_original_rank_full_input_artifact(
            feat_zip + b"tampered", expected=feat_api,
            original_rank=_verify_rank(rank_zip, rank_api),
        )


def test_rank_and_full_feature_artifacts_must_share_same_genuine_worker(
    tmp_path: Path,
) -> None:
    rank_zip, rank_api, feat_zip, feat_api = _fixture(tmp_path)
    with pytest.raises(OriginalRankFeatureArtifactError, match="identities differ"):
        verify_github_original_rank_full_input_artifact(
            feat_zip,
            expected=replace(
                feat_api,
                run_id=RUN + 1,
                artifact_run_id=RUN + 1,
                artifact_name=(
                    f"continuous-paper-first-seen-short-rank-full-inputs-{RUN+1}-1"
                ),
            ),
            original_rank=_verify_rank(rank_zip, rank_api),
        )


def test_outer_zip_extra_file_is_rejected_even_with_recomputed_github_sha(
    tmp_path: Path,
) -> None:
    rank_zip, rank_api, feat_zip, feat_api = _fixture(tmp_path)
    forged = _rebuilt(feat_zip, "overrides.json", b"{}")
    with pytest.raises(OriginalRankFeatureArtifactError, match="extra"):
        verify_github_original_rank_full_input_artifact(
            forged, expected=_new_binding(forged, feat_api),
            original_rank=_verify_rank(rank_zip, rank_api),
        )


def test_self_resealed_modified_feature_payload_still_fails_original_id(
    tmp_path: Path,
) -> None:
    rank_zip, rank_api, feat_zip, feat_api = _fixture(tmp_path)
    original = _verify_rank(rank_zip, rank_api)
    with zipfile.ZipFile(io.BytesIO(feat_zip)) as outer:
        original_inner = outer.read(BUNDLE_FILE)
        original_receipt = json.loads(outer.read(RECEIPT_FILE))
    with zipfile.ZipFile(io.BytesIO(original_inner)) as bundle:
        files = {
            name: bundle.read(name) for name in bundle.namelist()
        }
    filename = next(name for name in files if name.startswith("batches/"))
    row = json.loads(files[filename])
    row["features"][0]["feature"]["funding"] = "0.99"
    files[filename] = (
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    tampered_inner = _outer(files)
    original_receipt["zip_sha256"] = hashlib.sha256(tampered_inner).hexdigest()
    original_receipt["zip_size_bytes"] = len(tampered_inner)
    receipt_bytes = (
        json.dumps(original_receipt, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    forged = _outer({
        RECEIPT_FILE: receipt_bytes,
        BUNDLE_FILE: tampered_inner,
    })
    with pytest.raises(OriginalRankFeatureArtifactError):
        verify_github_original_rank_full_input_artifact(
            forged, expected=_new_binding(forged, feat_api),
            original_rank=original,
        )
