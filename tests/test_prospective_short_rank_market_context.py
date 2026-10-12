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
