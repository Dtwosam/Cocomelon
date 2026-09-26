from __future__ import annotations

import json
from pathlib import Path

from cocomelon.learning_shadow_replay_cli import main
from tests.test_learning_shadow_replay import _run_kwargs


def _common(kwargs: dict[str, object]) -> list[str]:
    return [
        "--recording-root",
        str(kwargs["recording_root"]),
        "--bundle",
        str(kwargs["bundle_path"]),
        "--output-root",
        str(kwargs["output_root"]),
        "--shadow-evidence-root",
        str(kwargs["shadow_evidence_root"]),
        "--shadow-admission",
        str(kwargs["shadow_admission_path"]),
        "--review-decision",
        str(kwargs["review_decision_path"]),
        "--review-dossier",
        str(kwargs["review_dossier_path"]),
        "--package-root",
        str(kwargs["package_root"]),
        "--validation-spec",
        str(kwargs["validation_spec_path"]),
        "--validation-score",
        str(kwargs["validation_score_path"]),
        "--finalization",
        str(kwargs["finalization_path"]),
        "--clean-evidence-root",
        str(kwargs["clean_evidence_root"]),
    ]


def test_learning_shadow_replay_cli_runs_and_verifies_without_economic_output(
    tmp_path,
    capsys,
) -> None:
    kwargs = _run_kwargs(tmp_path)
    status = main(
        [
            "run",
            *_common(kwargs),
            "--runtime-code-revision",
            str(kwargs["runtime_code_revision"]),
            "--evidence-eligible-at-ms",
            str(kwargs["evidence_eligible_at_ms"]),
        ]
    )
    assert status == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["command"] == "learning-shadow-replay"
    assert run_payload["action"] == "run"
    assert run_payload["closed_paper_trade_count"] == 0
    assert run_payload["promotion_eligible"] is False
    assert run_payload["execution_ready"] is False
    assert run_payload["live_promotion_authorized"] is False
    for forbidden in ("net_r", "net_pnl", "profit_factor", "drawdown"):
        assert forbidden not in run_payload

    receipt_path = (
        Path(str(kwargs["output_root"])) / "shadow-replay-receipt.json"
    )
    status = main(
        [
            "verify",
            *_common(kwargs),
            "--receipt",
            str(receipt_path),
        ]
    )
    assert status == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["receipt_id"] == run_payload["receipt_id"]
    assert verify_payload["shadow_campaign_id"] == run_payload["shadow_campaign_id"]
