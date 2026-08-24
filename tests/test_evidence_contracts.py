from __future__ import annotations

from contextlib import nullcontext
from decimal import ROUND_UP, Context, Decimal, localcontext

import pytest

from cocomelon.config import MAINNET_API_URL, MAINNET_WS_URL
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, SourceSegment
from cocomelon.evidence.contracts import (
    BaselineReplayConfig,
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    FrozenBaselineReplayBundle,
    SelectedEvidenceMarket,
    baseline_manifest_config_digest,
)


def _selected(coin: str, rank: int, score: str = "50") -> SelectedEvidenceMarket:
    return SelectedEvidenceMarket(
        market=MarketId("", coin),
        rank=rank,
        feature_snapshot_id=f"feature-{coin.lower()}",
        score=Decimal(score),
    )


def _session(
    selected: tuple[SelectedEvidenceMarket, ...] | None = None,
) -> EvidenceRecordingSession:
    config = EvidenceRecordingConfig(duration_seconds=3_600)
    return EvidenceRecordingSession(
        started_at_ms=1_787_573_000_000,
        recorder_code_revision="a" * 40,
        selected=selected or (_selected("BTC", 1), _selected("ETH", 2)),
        recording_config_digest=config.config_digest,
        api_url=MAINNET_API_URL,
        ws_url=MAINNET_WS_URL,
        selection_policy_id=config.selection_policy_id,
    )


def _segment() -> SourceSegment:
    return SourceSegment(
        relative_path="events/2026-08-24/l2_book/BTC/segment-000001.jsonl",
        partition="events/2026-08-24/l2_book/BTC",
        sha256="b" * 64,
        byte_count=100,
        row_count=1,
        schema_version=1,
        first_available_at_ms=1_000,
        last_available_at_ms=1_000,
    )


def _manifest(config_digest: str) -> ReplayManifest:
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_000,
        end_ms=2_000,
        segments=(_segment(),),
        gap_refs=(),
        code_revision="c" * 40,
        config_digest=config_digest,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="hyperliquid-native-base-2026-08-23",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def test_recording_config_has_locked_mainnet_defaults_and_stable_digest() -> None:
    config = EvidenceRecordingConfig(duration_seconds=3_600)

    assert config.api_url == MAINNET_API_URL
    assert config.ws_url == MAINNET_WS_URL
    assert config.deep_limit == 20
    assert config.context_poll_seconds == 60
    assert config.funding_poll_seconds == 60
    assert config.warmup_5m_bars == 25
    assert config.warmup_15m_bars == 25
    assert config.candle_intervals == ("1m", "5m", "15m")
    assert config.selection_policy_id == "rankable-native-top-v1"
    assert config.config_version == "phase9-evidence-v1"
    assert len(config.config_digest) == 64


def test_recording_config_rejects_non_mainnet_or_invalid_capacity() -> None:
    invalid_kwargs = (
        {"duration_seconds": 0},
        {"duration_seconds": 1, "deep_limit": 0},
        {"duration_seconds": 1, "deep_limit": 134},
        {"duration_seconds": 1, "context_poll_seconds": 0},
        {"duration_seconds": 1, "funding_poll_seconds": 0},
        {"duration_seconds": 1, "warmup_5m_bars": 0},
        {"duration_seconds": 1, "warmup_15m_bars": 0},
        {"duration_seconds": 1, "api_url": "https://api.hyperliquid-testnet.xyz"},
        {"duration_seconds": 1, "api_url": "https://example.com"},
        {"duration_seconds": 1, "ws_url": "wss://example.com/ws"},
    )
    for kwargs in invalid_kwargs:
        with pytest.raises(ValueError):
            EvidenceRecordingConfig(**kwargs)


def test_selected_market_validates_rank_score_and_native_execution_namespace() -> None:
    assert _selected("BTC", 1, "72.5").score == Decimal("72.5")

    with pytest.raises(ValueError, match="rank"):
        _selected("BTC", 0)
    with pytest.raises(ValueError, match="score"):
        _selected("BTC", 1, "101")
    with pytest.raises(ValueError, match="native"):
        SelectedEvidenceMarket(
            market=MarketId("hip3", "hip3:ABC"),
            rank=1,
            feature_snapshot_id="feature",
            score=Decimal("50"),
        )


def test_recording_session_id_is_enumeration_stable() -> None:
    first = _session((_selected("ETH", 2), _selected("BTC", 1)))
    second = _session((_selected("BTC", 1), _selected("ETH", 2)))

    assert first.selected == second.selected
    assert first.session_id == second.session_id
    assert len(first.session_id) == 64


def test_recording_session_rejects_duplicate_market_or_rank() -> None:
    with pytest.raises(ValueError, match="duplicate market"):
        _session((_selected("BTC", 1), _selected("BTC", 2)))
    with pytest.raises(ValueError, match="duplicate rank"):
        _session((_selected("BTC", 1), _selected("ETH", 1)))


def test_baseline_config_digest_ignores_ambient_decimal_context() -> None:
    expected = BaselineReplayConfig().config_digest

    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        actual = BaselineReplayConfig().config_digest

    assert actual == expected
    assert len(actual) == 64


def test_baseline_config_has_locked_research_defaults() -> None:
    config = BaselineReplayConfig()

    assert config.starting_cash == Decimal("10000")
    assert config.decision_interval == "15m"
    assert config.decision_grace_ms == 30_000
    assert config.microstructure_window_ms == 60_000
    assert config.correlation_bucket == "crypto_beta"
    assert config.liquidation_policy_id == "paper-leverage-distance-v1"
    assert config.feature_version == "phase4-v1"
    assert config.strategy_version == "phase5-v1"
    assert config.risk_version == "phase6-v1"
    assert config.replay_engine_version == "phase8-v1"
    assert config.config_version == "phase9-baseline-replay-v1"


def test_baseline_config_rejects_invalid_research_settings() -> None:
    cases = (
        {"starting_cash": Decimal("0")},
        {"decision_interval": "5m"},
        {"decision_grace_ms": -1},
        {"microstructure_window_ms": 0},
        {"correlation_bucket": ""},
    )
    for kwargs in cases:
        with pytest.raises(ValueError):
            BaselineReplayConfig(**kwargs)


def test_bundle_binds_manifest_to_raw_replay_config_and_session() -> None:
    replay_config = BaselineReplayConfig()
    session_digest = _session().session_id
    config_digest = baseline_manifest_config_digest(replay_config, session_digest)
    manifest = _manifest(config_digest)

    bundle = FrozenBaselineReplayBundle(
        manifest=manifest,
        replay_config=replay_config,
        recording_session_digest=session_digest,
        source_set_digest="d" * 64,
    )

    assert bundle.manifest.config_digest == config_digest
    assert len(bundle.bundle_id) == 64


def test_bundle_rejects_manifest_config_digest_mismatch() -> None:
    replay_config = BaselineReplayConfig()
    session_digest = _session().session_id

    with pytest.raises(ValueError, match="config_digest"):
        FrozenBaselineReplayBundle(
            manifest=_manifest("0" * 64),
            replay_config=replay_config,
            recording_session_digest=session_digest,
            source_set_digest="d" * 64,
        )


def test_bundle_rejects_non_sha_provenance_digests() -> None:
    replay_config = BaselineReplayConfig()
    session_digest = _session().session_id
    manifest = _manifest(baseline_manifest_config_digest(replay_config, session_digest))

    for field in ("recording_session_digest", "source_set_digest"):
        kwargs = {
            "manifest": manifest,
            "replay_config": replay_config,
            "recording_session_digest": session_digest,
            "source_set_digest": "d" * 64,
        }
        kwargs[field] = "not-a-sha"
        with pytest.raises(ValueError):
            FrozenBaselineReplayBundle(**kwargs)


def test_contracts_do_not_depend_on_wall_clock() -> None:
    first = (_session().session_id, BaselineReplayConfig().config_digest)
    with nullcontext():
        second = (_session().session_id, BaselineReplayConfig().config_digest)
    assert first == second
