from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_preset_cli as cli
from cocomelon.config import ExecutionMode
from cocomelon.research.historical_archive_presets import JUL_SEP_2026_V2


class ForbiddenSettings:
    @classmethod
    def from_env(cls) -> object:
        raise AssertionError("offline commands must not read runtime settings")


class LiveSettings:
    execution_mode = ExecutionMode.LIVE


def test_show_is_offline_and_emits_frozen_preset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("show must not construct a Hyperliquid client")
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_archive_experiment_preset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("show must not run an experiment")
        ),
    )

    status = cli.main(["show"])

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "show"
    assert payload["paid_request_performed"] is False
    assert payload["name"] == JUL_SEP_2026_V2.name
    assert payload["preset_id"] == JUL_SEP_2026_V2.preset_id
    assert payload["archive_shard_count"] == 1_968
    assert payload["evidence_class"] == "touched_development"


def test_keys_is_offline_and_bound_to_frozen_preset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("keys must not construct a Hyperliquid client")
        ),
    )

    status = cli.main(["keys"])

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "keys"
    assert payload["paid_request_performed"] is False
    assert payload["preset"] == JUL_SEP_2026_V2.name
    assert payload["preset_id"] == JUL_SEP_2026_V2.preset_id
    assert payload["shard_count"] == 1_968
    assert len(payload["keys"]) == 1_968
    assert payload["keys"][0].endswith("/20260701/0.lz4")
    assert payload["keys"][-1].endswith("/20260920/23.lz4")


def test_show_rejects_unknown_preset_without_runtime_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)

    status = cli.main(["show", "--preset", "missing"])

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error_type"] == "ValueError"
    assert "unknown archive experiment preset" in payload["error"]


def test_run_rejects_live_mode_before_client_or_experiment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    class FakeSettings:
        @classmethod
        def from_env(cls) -> LiveSettings:
            return LiveSettings()

    monkeypatch.setattr(cli, "Settings", FakeSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("live mode must fail before InfoClient construction")
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_archive_experiment_preset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("live mode must fail before experiment execution")
        ),
    )

    status = cli.main(
        [
            "run",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(tmp_path / "output"),
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error"] == "historical archive presets require paper execution mode"



def test_run_emits_preset_run_receipt_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    class PaperSettings:
        execution_mode = ExecutionMode.PAPER

    class FakeSettings:
        @classmethod
        def from_env(cls) -> PaperSettings:
            return PaperSettings()

    result = SimpleNamespace(
        archive=SimpleNamespace(
            manifest_id="archive-manifest",
            shard_count=1968,
            total_byte_count=123,
        ),
        overlap=SimpleNamespace(
            report_id="overlap-report",
            compared_count=384,
        ),
        dataset_id="dataset-id",
        report_id="comparison-report-id",
        comparison=SimpleNamespace(
            comparison_version="historical-model-comparison-v7",
            dataset_row_count=24000,
            baseline_folds=(object(), object()),
        ),
    )
    monkeypatch.setattr(cli, "Settings", FakeSettings)
    monkeypatch.setattr(cli, "InfoClient", lambda _settings: object())
    monkeypatch.setattr(
        cli,
        "run_archive_experiment_preset",
        lambda *args, **kwargs: result,
    )
    monkeypatch.setattr(
        cli,
        "build_archive_preset_run_receipt",
        lambda *args, **kwargs: SimpleNamespace(receipt_id="r" * 64),
    )

    output_root = tmp_path / "output"
    status = cli.main(
        [
            "run",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(output_root),
            "--received-at-ms",
            "123",
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["preset"] == JUL_SEP_2026_V2.name
    assert payload["preset_id"] == JUL_SEP_2026_V2.preset_id
    assert payload["preset_run_receipt_id"] == "r" * 64
    assert payload["preset_run_receipt"] == str(output_root / "preset-run.json")
    assert payload["comparison_version"] == "historical-model-comparison-v7"

def test_clock_rejects_negative_fixed_retrieval_time() -> None:
    with pytest.raises(ValueError, match="received_at_ms must be non-negative"):
        cli._clock(-1)
