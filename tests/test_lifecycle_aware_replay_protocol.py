from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.evidence import cli_support as evidence_cli_support
from cocomelon.evidence.cli_support import (
    LIFECYCLE_AWARE_CONFIG_VERSION,
    LIFECYCLE_AWARE_REPLAY_ENGINE_VERSION,
    LIFECYCLE_ENTRY_WINDOW_MS,
    lifecycle_new_exposure_cutoff_ms,
    replay_config_for_protocol,
)
from cocomelon.evidence.contracts import BaselineReplayConfig


def test_lifecycle_aware_protocol_freezes_versions_without_changing_strategy_semantics() -> None:
    baseline = BaselineReplayConfig(starting_cash=Decimal("10000"))
    lifecycle = replay_config_for_protocol(
        Decimal("10000"),
        lifecycle_aware=True,
    )

    assert lifecycle.replay_engine_version == LIFECYCLE_AWARE_REPLAY_ENGINE_VERSION
    assert lifecycle.config_version == LIFECYCLE_AWARE_CONFIG_VERSION
    assert lifecycle.feature_version == baseline.feature_version
    assert lifecycle.strategy_version == baseline.strategy_version
    assert lifecycle.risk_version == baseline.risk_version
    assert lifecycle.execution == baseline.execution
    assert lifecycle.execution.config_version == "phase7-v1"
    assert lifecycle.execution.max_position_age_ms is None
    assert lifecycle.risk_limits == baseline.risk_limits
    assert lifecycle.eligibility == baseline.eligibility


def test_thesis_expiry_protocol_has_distinct_frozen_identity() -> None:
    assert evidence_cli_support.THESIS_EXPIRY_MS == 14_400_000
    assert (
        evidence_cli_support.THESIS_EXPIRY_REPLAY_ENGINE_VERSION
        == "phase8-v3-thesis-expiry"
    )
    assert (
        evidence_cli_support.THESIS_EXPIRY_CONFIG_VERSION
        == "phase9-baseline-replay-v3-thesis-expiry"
    )
    assert (
        evidence_cli_support.THESIS_EXPIRY_EXECUTION_CONFIG_VERSION
        == "phase7-v2-4h-thesis-expiry"
    )


def test_thesis_expiry_replay_config_changes_only_explicit_v4_semantics() -> None:
    baseline = BaselineReplayConfig(starting_cash=Decimal("10000"))
    v4 = evidence_cli_support.thesis_expiry_replay_config(Decimal("10000"))

    assert v4.replay_engine_version == "phase8-v3-thesis-expiry"
    assert v4.config_version == "phase9-baseline-replay-v3-thesis-expiry"
    assert v4.execution.config_version == "phase7-v2-4h-thesis-expiry"
    assert v4.execution.max_position_age_ms == 14_400_000
    assert v4.feature_version == baseline.feature_version
    assert v4.strategy_version == baseline.strategy_version
    assert v4.risk_version == baseline.risk_version
    assert v4.risk_limits == baseline.risk_limits
    assert v4.eligibility == baseline.eligibility
    assert v4.execution.latency_ms == baseline.execution.latency_ms
    assert v4.execution.max_ioc_slippage_bps == baseline.execution.max_ioc_slippage_bps
    assert v4.execution.taker_fee_rate == baseline.execution.taker_fee_rate
    assert v4.execution.fee_schedule_id == baseline.execution.fee_schedule_id


def test_lifecycle_aware_cutoff_is_fixed_from_recording_session_start() -> None:
    config = replay_config_for_protocol(Decimal("10000"), lifecycle_aware=True)
    started_at_ms = 1_800_000_000_000

    assert lifecycle_new_exposure_cutoff_ms(config, started_at_ms) == (
        started_at_ms + LIFECYCLE_ENTRY_WINDOW_MS
    )


def test_legacy_replay_has_no_new_exposure_cutoff() -> None:
    config = replay_config_for_protocol(Decimal("10000"), lifecycle_aware=False)
    assert lifecycle_new_exposure_cutoff_ms(config, 123_456) is None


def test_lifecycle_version_pair_must_be_consistent() -> None:
    mismatched = BaselineReplayConfig(
        replay_engine_version=LIFECYCLE_AWARE_REPLAY_ENGINE_VERSION,
    )
    with pytest.raises(ValueError, match="lifecycle-aware replay config version"):
        lifecycle_new_exposure_cutoff_ms(mismatched, 123_456)
