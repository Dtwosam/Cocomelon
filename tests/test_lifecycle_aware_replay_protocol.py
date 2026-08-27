from __future__ import annotations

from decimal import Decimal

import pytest

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
    assert lifecycle.risk_limits == baseline.risk_limits
    assert lifecycle.eligibility == baseline.eligibility


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
