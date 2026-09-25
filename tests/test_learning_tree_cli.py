from __future__ import annotations

import json

import pytest

pytest.importorskip("sklearn")

from cocomelon.learning_tree_cli import main
from cocomelon.research.learning_challenger_run import (
    write_learning_challenger_run_manifest,
)
from cocomelon.research.learning_training_bundle import write_learning_training_bundle
from tests.test_learning_tree import _bundle, _manifest, _row


def _inputs(tmp_path):
    rows = tuple(
        _row(index, feature_value="0.9", target_value="0.05")
        for index in range(1, 49)
    )
    manifest = _manifest(rows)
    bundle = _bundle(rows, manifest)
    training_dir = tmp_path / "training"
    write_learning_training_bundle(
        bundle.training_set,
        output_dir=training_dir,
    )
    manifest_path = write_learning_challenger_run_manifest(
        tmp_path / "challenger-run.json",
        manifest,
    )
    return training_dir, manifest_path


def test_learning_tree_cli_writes_research_only_report(tmp_path, capsys) -> None:
    training_dir, manifest_path = _inputs(tmp_path)
    output = tmp_path / "tree-evaluation.json"

    code = main(
        (
            "--training-bundle-dir",
            str(training_dir),
            "--run-manifest",
            str(manifest_path),
            "--output",
            str(output),
        )
    )

    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert emitted["evaluation_id"] == report["evaluation_id"]
    assert emitted["train_row_count"] == 40
    assert emitted["validation_row_count"] == 8
    assert emitted["validation_trade_count"] == 8
    assert emitted["validation_mean_target"] == "0.05"
    assert emitted["qualifies_development"] is True
    assert report["research_only"] is True
    assert report["promotion_eligible"] is False
    assert report["execution_ready"] is False


def test_learning_tree_cli_refuses_conflicting_report_rewrite(tmp_path, capsys) -> None:
    training_dir, manifest_path = _inputs(tmp_path)
    output = tmp_path / "tree-evaluation.json"
    output.write_text('{"tampered":true}\n', encoding="utf-8")

    code = main(
        (
            "--training-bundle-dir",
            str(training_dir),
            "--run-manifest",
            str(manifest_path),
            "--output",
            str(output),
        )
    )

    assert code == 2
    emitted = json.loads(capsys.readouterr().err)
    assert "EVALUATION_CONFLICT" in emitted["error"]
