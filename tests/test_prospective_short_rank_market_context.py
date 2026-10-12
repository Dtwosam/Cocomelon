from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.seal_paper_short_rank_market_context as original_context_sealer
from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.evidence.recording import _startup_ranks
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
    OriginalRankFeatureInputBatchStore,
    OriginalRankInputBatchError,
)
from cocomelon.research.prospective_short_rank_full_feature_artifact import (
    VerifiedGithubOriginalRankInputs,
)
from cocomelon.research.prospective_short_rank_market_context_artifact import (
    ExpectedGithubRankContextArtifact,
    OriginalRankContextArtifactError,
    verify_github_original_rank_market_context_artifact,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    VerifiedGithubShortRankEvidence,
)
from scripts.audit_paper_short_rank_market_context import (
    audit_original_worker_rank_context_sources,
)
from cocomelon.research.prospective_short_rank_market_context import (
    OriginalRankEligibilityContextBatch,
    OriginalRankEligibilityContextError,
    OriginalRankEligibilityContextStore,
    replay_recorded_rank_eligibility,
)
from scripts.seal_paper_short_rank_market_context import (
    BUNDLE_FILE,
    RECEIPT_FILE,
    seal_original_rank_market_context,
)

OBSERVED = 1_790_080_000_000
D = Decimal


def _market(
    market: str, *,
    is_delisted: bool = False,
    max_leverage: int = 20,
    mid_px: str = "100",
    received_at_ms: int = OBSERVED - 100,
    oi: str = "100000",
    volume: str = "1000000",
) -> PerpMarketSnapshot:
    key = MarketId("", market)
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=key, wire_name=market, sz_decimals=4,
            max_leverage=max_leverage, margin_table_id=None,
            only_isolated=False, is_delisted=is_delisted, margin_mode=None,
        ),
        context=PerpMarketContext(
            market=key, mark_px=D("100"),
            mid_px=D(mid_px), oracle_px=D("100"),
            funding=D("0.0001"), open_interest=D(oi),
            day_ntl_vlm=D(volume), premium=D("0.005"),
            prev_day_px=D("98"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _sources() -> tuple[
    FirstSeenRankSnapshot, OriginalRankFeatureInputBatch,
    OriginalRankEligibilityContextBatch, dict[str, PerpMarketSnapshot],
]:
    markets = {
        "BTC": _market("BTC", volume="2000000", oi="200000"),
        "ETH": _market("ETH", is_delisted=True),
        "SOL": _market("SOL", max_leverage=0),
        "AAVE": _market("AAVE", mid_px="102"),
    }
    features, ranks = _startup_ranks(markets, as_of_ms=OBSERVED)
    rank = FirstSeenRankSnapshot.from_observation(
        observed_at_ms=OBSERVED,
        captured_at_ms=OBSERVED + 20,
        features=features,
        ranks=ranks,
    )
    full = OriginalRankFeatureInputBatch.from_original_rank(rank, features)
    context = OriginalRankEligibilityContextBatch.from_original_rank(rank, markets)
    return rank, full, context, markets


def test_real_production_rankable_universe_can_be_replayed_from_context() -> None:
    rank, features, context, _ = _sources()
    assert len(rank.ranks) == 2
    result = replay_recorded_rank_eligibility(
        rank=rank, feature_inputs=features, context=context,
    )
    assert result["original_rank_membership_from_recorded_context_recomputed"]
    assert result["recorded_context_markets_examined"] == 4
    assert result["rankable_markets_from_recorded_context"] == 2
    assert result["original_market_context_independently_authenticated"] is False
    assert result["profitable_risk_matched_account_certified"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


@pytest.mark.parametrize("case", [
    "delisting", "leverage", "invalid_price", "context_age", "feature_cash",
])
def test_modified_context_or_feature_source_cannot_recreate_claimed_rank_set(
    case: str,
) -> None:
    rank, features, context, _ = _sources()
    snapshots = list(context.snapshots)
    # AAVE and BTC are actually rankable; self-consistent rewrites of their
    # provenance cannot make a falsely unrankable ranking eligible.
    index = next(i for i, row in enumerate(snapshots)
                 if row.meta.market.canonical == "AAVE")
    original = snapshots[index]
    if case == "delisting":
        snapshots[index] = replace(
            original, meta=replace(original.meta, is_delisted=True),
        )
    elif case == "leverage":
        snapshots[index] = replace(
            original, meta=replace(original.meta, max_leverage=0),
        )
    elif case == "invalid_price":
        snapshots[index] = replace(
            original, context=replace(original.context, oracle_px=None),
        )
    elif case == "context_age":
        snapshots[index] = replace(
            original, received_at_ms=OBSERVED - 70_000,
        )
        # Changing the receive timestamp also invalidates the parent rank.
        with pytest.raises(OriginalRankEligibilityContextError, match="disagrees"):
            replace(context, snapshots=tuple(snapshots)).bind_to(rank)
        return
    else:
        idx = next(i for i, feat in enumerate(features.features)
                   if feat.market.canonical == "AAVE")
        forged = list(features.features)
        forged[idx] = replace(
            forged[idx], day_notional_volume=D("1000010"),
        )
        edited = replace(features, features=tuple(forged))
        with pytest.raises(OriginalRankInputBatchError):
            replay_recorded_rank_eligibility(
                rank=rank, feature_inputs=edited, context=context,
            )
        return
    edited = replace(context, snapshots=tuple(snapshots))
    with pytest.raises(
        OriginalRankEligibilityContextError,
        match="cannot reproduce rank features|contradicts",
    ):
        replay_recorded_rank_eligibility(
            rank=rank, feature_inputs=features, context=edited,
        )


def test_immutable_market_context_store_preserves_original_bytes(
    tmp_path: Path,
) -> None:
    rank, full, context, markets = _sources()
    store = OriginalRankEligibilityContextStore(tmp_path / "market-context")
    assert store.append(context)
    assert not store.append(context)
    assert store.source_digest
    restored = OriginalRankEligibilityContextStore(tmp_path / "market-context")
    assert restored.iter_verified() == (context,)
    assert restored.source_digest == store.source_digest
    assert context.to_dict() == OriginalRankEligibilityContextBatch.from_dict(
        context.to_dict()
    ).to_dict()
    # A new rank with different original input cannot rewrite an old suffix.
    tampered = replace(
        context,
        snapshots=(
            replace(context.snapshots[0], source="not-original-source"),
            *context.snapshots[1:],
        ),
    )
    with pytest.raises(OriginalRankEligibilityContextError, match="conflicts"):
        restored.append(tampered)
    raw_file = next((tmp_path / "market-context" / "batches").glob("*.json"))
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
    raw["snapshots"][0]["meta"]["is_delisted"] = True
    raw_file.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(OriginalRankEligibilityContextError):
        OriginalRankEligibilityContextStore(tmp_path / "market-context")


def test_old_rank_context_never_backfilled_or_reordered(tmp_path: Path) -> None:
    rank, full, context, markets = _sources()
    store = OriginalRankEligibilityContextStore(tmp_path / "contexts")
    future = replace(
        context, observed_at_ms=OBSERVED + 50_000,
        captured_at_ms=OBSERVED + 50_020,
    )
    assert store.append(future)
    with pytest.raises(
        OriginalRankEligibilityContextError, match="backdated",
    ):
        store.append(context)
    no_context = {key: value for key, value in markets.items() if key != "AAVE"}
    with pytest.raises(
        OriginalRankEligibilityContextError, match="missing original",
    ):
        OriginalRankEligibilityContextBatch.from_original_rank(rank, no_context)
    with pytest.raises(
        OriginalRankEligibilityContextError, match="disagrees",
    ):
        replace(context, rank_snapshot_digest="a" * 64).bind_to(rank)


def test_live_capture_path_keeps_eligibility_sidecar_separate_from_orders() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8",
    )
    assert "OriginalRankEligibilityContextStore(" in source
    assert "OriginalRankEligibilityContextBatch.from_original_rank(" in source
    assert "prospective-short-rank-market-context-error.json" in source
    assert "markets=snapshots" in source
    assert "markets=refreshed" in source
    assert source.count("capture_rank_first_seen(") == 4
    assert source.count("            markets=") >= 2
    assert '"execution_authority": False' in source


def _seal_setup(
    root: Path, *,
    include_context: bool = True,
) -> OriginalRankEligibilityContextBatch:
    rank, full, context, _ = _sources()
    rank_store = FirstSeenRankSnapshotStore(
        root / "prospective-short-rank-first-seen"
    )
    assert rank_store.append(rank)
    full_store = OriginalRankFeatureInputBatchStore(
        root / "prospective-short-rank-full-feature-inputs"
    )
    assert full_store.append(full)
    if include_context:
        context_store = OriginalRankEligibilityContextStore(
            root / "prospective-short-rank-market-context"
        )
        assert context_store.append(context)
    return context


def _seal_context(root: Path, out: Path) -> dict[str, object]:
    return seal_original_rank_market_context(
        root, out, worker_run_id=38230091014,
        worker_run_attempt=1, worker_head_sha="a" * 40,
        sealed_at_ms=OBSERVED + 1000,
    )


def test_local_full_context_seal_checks_all_original_market_memberships(
    tmp_path: Path,
) -> None:
    import hashlib
    import zipfile

    root, out = tmp_path / "worker", tmp_path / "seal"
    context = _seal_setup(root)
    unchanged = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.json")
    }
    proof = _seal_context(root, out)
    assert proof["original_rank_market_context_status"] == (
        "locally_sealed_prospective_suffix"
    )
    assert proof["local_original_eligibility_membership_replayed"] is True
    assert proof["verified_market_context_batches"] == 1
    assert proof["rank_snapshots_without_context"] == 0
    assert proof["independent_mainnet_market_stream_authenticated"] is False
    assert proof["execution_authority"] is False
    assert proof["promotion_authority"] is False
    assert hashlib.sha256((out / BUNDLE_FILE).read_bytes()).hexdigest() == (
        proof["zip_sha256"]
    )
    with zipfile.ZipFile(out / BUNDLE_FILE) as z:
        assert z.namelist() == [
            "manifest.json", f"batches/{OBSERVED:016d}.json",
        ]
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["source_context_markets_replayed"] == 4
        assert manifest["verified_market_context_batches"] == 1
        assert manifest["original_context_source_digest"] == proof[
            "original_context_source_digest"
        ]
        assert json.loads(z.read(f"batches/{OBSERVED:016d}.json")) == (
            context.to_dict()
        )
    assert unchanged == {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.json")
    }


def test_missing_original_market_context_never_backfilled(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "worker", tmp_path / "seal"
    _seal_setup(root, include_context=False)
    receipt = _seal_context(root, out)
    assert receipt["original_rank_market_context_status"] == "rejected"
    assert receipt["local_original_eligibility_membership_replayed"] is False
    assert receipt["failure_reason"]
    assert receipt["execution_authority"] is False
    assert not (out / BUNDLE_FILE).exists()
    assert (out / RECEIPT_FILE).is_file()


def test_context_mutation_during_seal_cannot_publish_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zipfile

    root, out = tmp_path / "worker", tmp_path / "seal"
    _seal_setup(root)
    context_path = next((
        root / "prospective-short-rank-market-context" / "batches"
    ).glob("*.json"))
    real_add = original_context_sealer._add_zip_file

    def tamper_after_manifest(
        archive: zipfile.ZipFile, name: str, data: bytes,
    ) -> None:
        real_add(archive, name, data)
        if name == "manifest.json":
            context_path.write_bytes(context_path.read_bytes() + b" ")

    monkeypatch.setattr(
        original_context_sealer, "_add_zip_file", tamper_after_manifest,
    )
    receipt = _seal_context(root, out)
    assert receipt["original_rank_market_context_status"] == "rejected"
    assert receipt["failure_reason"] == (
        "original rank market context changed during sealing"
    )
    assert receipt["zip_sha256"] is None
    assert receipt["promotion_authority"] is False
    assert not (out / BUNDLE_FILE).exists()
    assert (out / RECEIPT_FILE).is_file()


def test_real_worker_seals_context_after_full_inputs_before_learning() -> None:
    source = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8",
    )
    before = source.index("- name: Upload original SHORT rank full-input seal or rejection")
    seal = source.index("- name: Seal original SHORT rank market context after paper exit")
    upload = source.index("- name: Upload original SHORT rank market context seal or rejection")
    learning = source.index("- name: Export compact continuous decision facts")
    assert before < seal < upload < learning
    assert "scripts/seal_paper_short_rank_market_context.py" in source
    assert source.count("scripts/seal_paper_short_rank_market_context.py") >= 3
    assert "compression-level: 0" in source[upload:learning]
    assert "if-no-files-found: error" in source[upload:learning]


def _github_source_context(
    tmp_path: Path,
) -> tuple[
    bytes, ExpectedGithubRankContextArtifact,
    VerifiedGithubShortRankEvidence, VerifiedGithubOriginalRankInputs,
]:
    import hashlib
    import io
    import zipfile

    state, output = tmp_path / "worker", tmp_path / "sealed"
    rank, full, context, _ = _sources()
    _seal_setup(state)
    receipt = _seal_context(state, output)
    assert receipt["original_rank_market_context_status"] == (
        "locally_sealed_prospective_suffix"
    )
    worker_id = 38230091014
    head = "a" * 40
    rank_digest = FirstSeenRankSnapshotStore(
        state / "prospective-short-rank-first-seen"
    ).state_digest
    full_digest = OriginalRankFeatureInputBatchStore(
        state / "prospective-short-rank-full-feature-inputs"
    ).source_digest
    rank_evidence = VerifiedGithubShortRankEvidence(
        snapshots=(rank,), rank_state_digest=rank_digest,
        archive_sha256="b" * 64, worker_run_id=worker_id,
        worker_head_sha=head, worker_run_attempt=1,
    )
    feature_evidence = VerifiedGithubOriginalRankInputs(
        batches=(full,), historical_rank_snapshots_without_inputs=0,
        source_digest=full_digest, archive_sha256="c" * 64,
        original_rank_state_digest=rank_digest,
        worker_run_id=worker_id, worker_head_sha=head, worker_attempt=1,
    )
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_STORED) as zip_file:
        zip_file.writestr(RECEIPT_FILE, (output / RECEIPT_FILE).read_bytes())
        zip_file.writestr(BUNDLE_FILE, (output / BUNDLE_FILE).read_bytes())
    artifact = outer.getvalue()
    binding = ExpectedGithubRankContextArtifact(
        run_id=worker_id,
        run_attempt=1,
        head_sha=head,
        artifact_run_id=worker_id,
        artifact_head_sha=head,
        artifact_name=(
            "continuous-paper-first-seen-short-rank-market-context-"
            f"{worker_id}-1"
        ),
        artifact_digest="sha256:" + hashlib.sha256(artifact).hexdigest(),
        artifact_size_bytes=len(artifact),
    )
    assert context.batch_sha256
    return artifact, binding, rank_evidence, feature_evidence


def test_github_context_zip_independently_replays_exact_rankable_population(
    tmp_path: Path,
) -> None:
    artifact, bound, rank, full = _github_source_context(tmp_path)
    verified = verify_github_original_rank_market_context_artifact(
        artifact, expected=bound, original_rank=rank,
        original_features=full,
    )
    result = verified.receipt()
    assert result[
        "rankable_membership_reconstructed_from_github_bound_producer_context"
    ] is True
    assert result["verified_rank_context_batches"] == 1
    assert result["original_eligibility_markets_replayed"] == 4
    assert result["market_context_source_independently_authenticated_from_exchange"] is False
    assert result["original_full_account_after_cost_profitability_certified"] is False
    assert result["promotion_authority"] is False


def test_github_context_outer_bytes_and_identity_or_feature_digest_refuse(
    tmp_path: Path,
) -> None:
    import hashlib

    artifact, bound, rank, full = _github_source_context(tmp_path)
    with pytest.raises(OriginalRankContextArtifactError, match="digest"):
        verify_github_original_rank_market_context_artifact(
            artifact + b"unexpected", expected=bound,
            original_rank=rank, original_features=full,
        )
    with pytest.raises(OriginalRankContextArtifactError, match="metadata"):
        replace(bound, artifact_head_sha="c" * 40)
    with pytest.raises(OriginalRankContextArtifactError, match="identities"):
        verify_github_original_rank_market_context_artifact(
            artifact, expected=bound,
            original_rank=replace(rank, worker_head_sha="d" * 40),
            original_features=full,
        )
    with pytest.raises(OriginalRankContextArtifactError, match="receipt"):
        verify_github_original_rank_market_context_artifact(
            artifact, expected=bound, original_rank=rank,
            original_features=replace(full, source_digest="f" * 64),
        )
    assert hashlib.sha256(artifact).hexdigest() == bound.artifact_digest[7:]


def test_github_context_archive_recomputed_outer_sha_cannot_hide_tamper(
    tmp_path: Path,
) -> None:
    import hashlib
    import io
    import zipfile

    artifact, bound, rank, full = _github_source_context(tmp_path)
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(artifact)) as original, zipfile.ZipFile(
        result, "w", compression=zipfile.ZIP_STORED,
    ) as changed:
        for item in original.namelist():
            raw = original.read(item)
            if item == RECEIPT_FILE:
                payload = json.loads(raw)
                payload["original_rank_state_digest"] = "f" * 64
                raw = (json.dumps(
                    payload, sort_keys=True, separators=(",", ":"),
                ) + "\n").encode("utf-8")
            changed.writestr(item, raw)
    fake = result.getvalue()
    rehashed = replace(
        bound, artifact_size_bytes=len(fake),
        artifact_digest="sha256:" + hashlib.sha256(fake).hexdigest(),
    )
    with pytest.raises(OriginalRankContextArtifactError, match="receipt"):
        verify_github_original_rank_market_context_artifact(
            fake, expected=rehashed, original_rank=rank,
            original_features=full,
        )


def test_missing_context_artifact_is_durable_negative_api_receipt() -> None:
    report = audit_original_worker_rank_context_sources(
        run_id=38230091014,
        run_attempt=1,
        run_json=None,
        jobs_json=None,
        artifacts_json=None,
        rank_artifact_zip=b"fake",
        full_input_artifact_zip=b"fake",
        context_artifact_zip=None,
        expected_repository="Dtwosam/Cocomelon",
    )
    assert report["rank_market_context_audit_status"] == "unverified"
    assert report["failure_reason_code"] == "original_context_artifact_unavailable"
    assert report["all_three_original_worker_artifact_sha256s_verified"] is False
    assert report["rankable_market_membership_reconstructed_from_recorded_context"] is False
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False


def test_original_completed_run_audit_downloads_exact_third_source() -> None:
    workflow = Path(
        ".github/workflows/original-short-rank-source-audit.yml"
    ).read_text(encoding="utf-8")
    assert "continuous-paper-first-seen-short-rank-market-context-" in workflow
    assert "market-context-artifact.zip" in workflow
    assert "scripts.audit_paper_short_rank_market_context" in workflow
    assert "original-first-seen-short-rank-context-audit-" in workflow
    assert "if-no-files-found: warn" in workflow
