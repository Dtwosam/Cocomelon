from __future__ import annotations

import json
from decimal import Decimal
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


def test_verify_is_offline_and_emits_receipt_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("verify must not construct a Hyperliquid client")
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_preset_run_receipt",
        lambda *args, **kwargs: SimpleNamespace(receipt_id="v" * 64),
    )
    receipt_path = tmp_path / "preset-run.json"
    receipt_path.write_text("{}\n", encoding="utf-8")

    status = cli.main(
        [
            "verify",
            "--receipt",
            str(receipt_path),
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "verify"
    assert payload["valid"] is True
    assert payload["paid_request_performed"] is False
    assert payload["preset"] == JUL_SEP_2026_V2.name
    assert payload["receipt_id"] == "v" * 64


def test_preflight_is_offline_and_emits_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("preflight must not construct a Hyperliquid client")
        ),
    )
    monkeypatch.setattr(
        cli,
        "build_archive_preset_preflight",
        lambda *args, **kwargs: SimpleNamespace(
            to_dict=lambda: {
                "preset_name": JUL_SEP_2026_V2.name,
                "preset_id": JUL_SEP_2026_V2.preset_id,
                "evidence_class": "touched_development",
                "archive_manifest_id": "archive-manifest",
                "archive_shard_count": 1968,
                "archive_total_byte_count": 123456,
                "expected_archive_shard_count": 1968,
                "implementation_attestation_id": "i" * 64,
                "source_tree_sha256": "s" * 64,
                "source_file_count": 200,
                "source_cache_file_count": 0,
                "output_root_clean": True,
                "paid_request_performed": False,
                "schema_version": 1,
                "preflight_id": "p" * 64,
            }
        ),
    )

    status = cli.main(
        [
            "preflight",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(tmp_path / "output"),
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "preflight"
    assert payload["ready"] is True
    assert payload["paid_request_performed"] is False
    assert payload["archive_shard_count"] == 1968
    assert payload["preflight_id"] == "p" * 64



def test_freeze_candidate_is_offline_and_emits_non_executable_recipe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("freeze-candidate must not construct a client")
        ),
    )
    freeze = SimpleNamespace(
        candidate_id="a" * 64,
        candidate_kind="model_family_recipe",
        model_family="stable_tree",
        calibration_variant="shared",
        selection_policy="unique_qualified_variant_only",
        prospective_only=True,
        promotion_eligible=False,
        execution_ready=False,
        frozen_at_ms=123,
        validation_not_before_ms=456,
    )
    monkeypatch.setattr(
        cli,
        "build_archive_candidate_freeze",
        lambda *args, **kwargs: freeze,
    )
    freeze_path = tmp_path / "output" / "candidate-freeze.json"
    monkeypatch.setattr(
        cli,
        "write_archive_candidate_freeze",
        lambda *args, **kwargs: freeze_path,
    )

    status = cli.main(
        [
            "freeze-candidate",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(tmp_path / "output"),
            "--frozen-at-ms",
            "123",
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "freeze-candidate"
    assert payload["paid_request_performed"] is False
    assert payload["candidate_id"] == "a" * 64
    assert payload["candidate_kind"] == "model_family_recipe"
    assert payload["model_family"] == "stable_tree"
    assert payload["calibration_variant"] == "shared"
    assert payload["prospective_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["candidate_freeze"] == str(freeze_path)


def test_verify_candidate_freeze_is_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("verify-candidate-freeze must not construct a client")
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_candidate_freeze",
        lambda *args, **kwargs: SimpleNamespace(candidate_id="b" * 64),
    )

    output_root = tmp_path / "output"
    status = cli.main(
        [
            "verify-candidate-freeze",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(output_root),
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "verify-candidate-freeze"
    assert payload["paid_request_performed"] is False
    assert payload["valid"] is True
    assert payload["candidate_id"] == "b" * 64
    assert payload["candidate_freeze"] == str(
        output_root / "candidate-freeze.json"
    )

def test_review_is_offline_and_emits_only_qualified_variants(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("review must not construct a Hyperliquid client")
        ),
    )
    qualified = SimpleNamespace(
        model_family="stable_tree",
        calibration_variant="shared",
        total_test_trades=80,
        mean_realized_net_return=Decimal("0.004"),
        eligible_for_freeze_review=True,
    )
    rejected = SimpleNamespace(
        model_family="stable_horizon_ridge",
        calibration_variant="market",
        total_test_trades=70,
        mean_realized_net_return=Decimal("-0.001"),
        eligible_for_freeze_review=False,
    )
    result = SimpleNamespace(
        review_id="r" * 64,
        policy_id="p" * 64,
        status="freeze_review_available",
        promotion_eligible=False,
        variants=(qualified, rejected),
    )
    monkeypatch.setattr(
        cli,
        "build_archive_development_review",
        lambda *args, **kwargs: result,
    )
    review_path = tmp_path / "output" / "development-review.json"
    monkeypatch.setattr(
        cli,
        "write_archive_development_review",
        lambda *args, **kwargs: review_path,
    )

    status = cli.main(
        [
            "review",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(tmp_path / "output"),
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "review"
    assert payload["paid_request_performed"] is False
    assert payload["status"] == "freeze_review_available"
    assert payload["promotion_eligible"] is False
    assert payload["review_id"] == "r" * 64
    assert payload["review_policy_id"] == "p" * 64
    assert payload["qualified_variants"] == [
        {
            "model_family": "stable_tree",
            "calibration_variant": "shared",
            "total_test_trades": 80,
            "mean_realized_net_return": "0.004",
        }
    ]
    assert payload["review_path"] == str(review_path)

def test_verify_bundle_is_offline_and_emits_bundle_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("verify-bundle must not construct a Hyperliquid client")
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_preset_bundle_receipt",
        lambda *args, **kwargs: SimpleNamespace(bundle_id="b" * 64),
    )

    status = cli.main(
        [
            "verify-bundle",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(tmp_path / "output"),
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "verify-bundle"
    assert payload["valid"] is True
    assert payload["paid_request_performed"] is False
    assert payload["preset"] == JUL_SEP_2026_V2.name
    assert payload["bundle_id"] == "b" * 64



def test_run_prepared_is_offline_and_emits_verified_receipts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "Settings", ForbiddenSettings)
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("run-prepared must not construct a Hyperliquid client")
        ),
    )
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
    monkeypatch.setattr(
        cli,
        "run_prepared_archive_experiment_preset",
        lambda **kwargs: result,
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_preset_run_receipt",
        lambda *args, **kwargs: SimpleNamespace(receipt_id="r" * 64),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_preset_bundle_receipt",
        lambda *args, **kwargs: SimpleNamespace(bundle_id="b" * 64),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_preset_source_attestation",
        lambda *args, **kwargs: SimpleNamespace(
            attestation_id="i" * 64,
            source_tree_sha256="s" * 64,
            files=(object(), object()),
        ),
    )

    output_root = tmp_path / "output"
    status = cli.main(
        [
            "run-prepared",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(output_root),
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "run-prepared"
    assert payload["paid_request_performed"] is False
    assert payload["prepared_source_execution"] is True
    assert payload["preset"] == JUL_SEP_2026_V2.name
    assert payload["preset_run_receipt_id"] == "r" * 64
    assert payload["preset_bundle_id"] == "b" * 64
    assert payload["implementation_attestation_id"] == "i" * 64
    assert payload["source_file_count"] == 2
    assert payload["output_root"] == str(output_root)


def test_prepare_requires_paper_mode_before_client_construction(
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
            AssertionError("live prepare must fail before client construction")
        ),
    )

    status = cli.main(
        [
            "prepare",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--received-at-ms",
            "123",
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error"] == "historical archive presets require paper execution mode"


def test_prepare_emits_authenticated_source_preparation(
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

    preparation = SimpleNamespace(
        preparation_id="q" * 64,
        archive=SimpleNamespace(
            manifest_id="archive-manifest",
            shard_count=1968,
            total_byte_count=456,
        ),
        archive_ingest_manifest_id="archive-ingest",
        coverage_report_id="coverage-report",
        overlap=SimpleNamespace(
            report_id="overlap-report",
            compared_count=384,
        ),
    )
    monkeypatch.setattr(cli, "Settings", FakeSettings)
    monkeypatch.setattr(cli, "InfoClient", lambda _settings: object())
    monkeypatch.setattr(
        cli,
        "prepare_archive_experiment_preset",
        lambda *args, **kwargs: preparation,
    )

    source_root = tmp_path / "sources"
    status = cli.main(
        [
            "prepare",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(source_root),
            "--received-at-ms",
            "123",
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "prepare"
    assert payload["paid_request_performed"] is False
    assert payload["preset"] == JUL_SEP_2026_V2.name
    assert payload["preparation_id"] == "q" * 64
    assert payload["archive_shard_count"] == 1968
    assert payload["archive_ingest_manifest_id"] == "archive-ingest"
    assert payload["coverage_report_id"] == "coverage-report"
    assert payload["overlap_report_id"] == "overlap-report"
    assert payload["source_preparation"] == str(
        source_root / "source-preparation.json"
    )

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
        "verify_archive_preset_run_receipt",
        lambda *args, **kwargs: SimpleNamespace(receipt_id="r" * 64),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_preset_bundle_receipt",
        lambda *args, **kwargs: SimpleNamespace(bundle_id="b" * 64),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_preset_source_attestation",
        lambda *args, **kwargs: SimpleNamespace(
            attestation_id="i" * 64,
            source_tree_sha256="s" * 64,
            files=(object(), object(), object()),
        ),
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
    assert payload["preset_bundle_id"] == "b" * 64
    assert payload["preset_bundle_receipt"] == str(
        output_root / "preset-bundle.json"
    )
    assert payload["implementation_attestation_id"] == "i" * 64
    assert payload["source_tree_sha256"] == "s" * 64
    assert payload["source_file_count"] == 3
    assert payload["comparison_version"] == "historical-model-comparison-v7"

def test_clock_rejects_negative_fixed_retrieval_time() -> None:
    with pytest.raises(ValueError, match="received_at_ms must be non-negative"):
        cli._clock(-1)
