from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.domain.replay import EvidenceClass
from cocomelon.evidence import cli_support


def test_thesis_expiry_freeze_requires_lifecycle_aware_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="thesis expiry requires lifecycle-aware replay"):
        cli_support.freeze_baseline_replay_payload(
            tmp_path / "recording",
            tmp_path / "bundle.json",
            Decimal("10000"),
            thesis_expiry=True,
        )


def test_thesis_expiry_freeze_persists_v4_identity_and_limits(
    tmp_path,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_freeze(recording_root, *, replay_config, code_revision):  # type: ignore[no-untyped-def]
        observed["recording_root"] = recording_root
        observed["replay_config"] = replay_config
        observed["code_revision"] = code_revision
        return SimpleNamespace(
            bundle_id="bundle-v4",
            manifest=SimpleNamespace(
                manifest_id="manifest-v4",
                evidence_class=EvidenceClass.MICROSTRUCTURE,
                code_revision=code_revision,
            ),
            recording_session_digest="a" * 64,
            source_set_digest="b" * 64,
            replay_config=replay_config,
        )

    monkeypatch.setattr(cli_support, "resolve_code_revision", lambda *_args, **_kwargs: "c" * 40)
    monkeypatch.setattr(cli_support, "freeze_baseline_replay_bundle", fake_freeze)
    monkeypatch.setattr(cli_support, "write_baseline_replay_bundle", lambda *_args: None)
    monkeypatch.setattr(cli_support, "_attach_source_locator", lambda *_args, **_kwargs: None)

    payload = cli_support.freeze_baseline_replay_payload(
        tmp_path / "recording",
        tmp_path / "bundle.json",
        Decimal("10000"),
        lifecycle_aware=True,
        thesis_expiry=True,
    )

    config = observed["replay_config"]
    assert config.replay_engine_version == "phase8-v3-thesis-expiry"
    assert config.config_version == "phase9-baseline-replay-v3-thesis-expiry"
    assert config.execution.config_version == "phase7-v2-4h-thesis-expiry"
    assert config.execution.max_position_age_ms == 14_400_000
    assert payload["entry_window_ms"] == 2_700_000
    assert payload["max_position_age_ms"] == 14_400_000
    assert payload["network_access"] is False
    assert payload["live_orders"] is False
