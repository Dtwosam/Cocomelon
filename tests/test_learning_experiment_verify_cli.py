from __future__ import annotations

import json

from cocomelon.learning_experiment_verify_cli import main
from tests.test_learning_experiment import _run


def test_learning_experiment_verify_cli_accepts_valid_experiment(
    tmp_path,
    capsys,
) -> None:
    result, output_root = _run(tmp_path)

    code = main(("--output-root", str(output_root)))

    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["verified"] is True
    assert emitted["experiment_id"] == result.experiment_id
    assert emitted["evaluation_id"] == result.evaluation_id
    assert emitted["research_only"] is True
    assert emitted["promotion_eligible"] is False
    assert emitted["execution_ready"] is False


def test_learning_experiment_verify_cli_rejects_tampered_experiment(
    tmp_path,
    capsys,
) -> None:
    _result, output_root = _run(tmp_path)
    summary_path = output_root / "experiment.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["evaluation_id"] = "f" * 64
    summary_path.write_text(
        json.dumps(
            summary,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    code = main(("--output-root", str(output_root)))

    assert code == 2
    emitted = json.loads(capsys.readouterr().err)
    assert "IDENTITY_MISMATCH" in emitted["error"]
