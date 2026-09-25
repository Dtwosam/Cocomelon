from __future__ import annotations

import json

from cocomelon.learning_shadow_evidence_cli import main
from tests.test_learning_shadow_evidence import _record, _shadow_inputs


def _base_args(
    *,
    package_root,
    spec_path,
    clean_evidence_root,
    score_path,
    finalization_path,
    dossier_path,
    decision_path,
    admission_path,
    shadow_evidence_root,
) -> list[str]:
    return [
        "--shadow-admission",
        str(admission_path),
        "--review-decision",
        str(decision_path),
        "--review-dossier",
        str(dossier_path),
        "--package-root",
        str(package_root),
        "--validation-spec",
        str(spec_path),
        "--validation-score",
        str(score_path),
        "--finalization",
        str(finalization_path),
        "--clean-evidence-root",
        str(clean_evidence_root),
        "--shadow-evidence-root",
        str(shadow_evidence_root),
    ]


def test_learning_shadow_evidence_cli_records_without_economic_output(
    tmp_path,
    capsys,
) -> None:
    (
        package_root,
        spec_path,
        clean_evidence_root,
        score_path,
        finalization_path,
        dossier_path,
        _decision,
        decision_path,
        admission,
        admission_path,
    ) = _shadow_inputs(tmp_path)
    record = _record(admission=admission, index=1)
    record_path = tmp_path / "record.json"
    record_path.write_text(
        json.dumps(
            {**record.identity_payload(), "record_id": record.record_id},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    shadow_evidence_root = tmp_path / "shadow-evidence"

    status = main(
        [
            "record-execution",
            *_base_args(
                package_root=package_root,
                spec_path=spec_path,
                clean_evidence_root=clean_evidence_root,
                score_path=score_path,
                finalization_path=finalization_path,
                dossier_path=dossier_path,
                decision_path=decision_path,
                admission_path=admission_path,
                shadow_evidence_root=shadow_evidence_root,
            ),
            "--record-json",
            str(record_path),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-shadow-evidence"
    assert payload["action"] == "record-execution"
    assert payload["shadow_admission_id"] == admission.shadow_admission_id
    assert payload["closed_paper_trade_count"] == 1
    assert payload["created"] is True
    assert payload["minimum_closed_mainnet_paper_trades"] == 500
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["live_promotion_authorized"] is False
    assert "net_r" not in payload
    assert "net_pnl" not in payload
    assert "profit_factor" not in payload
    assert "drawdown" not in payload


def test_learning_shadow_evidence_cli_verifies_existing_store(
    tmp_path,
    capsys,
) -> None:
    (
        package_root,
        spec_path,
        clean_evidence_root,
        score_path,
        finalization_path,
        dossier_path,
        _decision,
        decision_path,
        _admission,
        admission_path,
    ) = _shadow_inputs(tmp_path)
    shadow_evidence_root = tmp_path / "shadow-evidence"

    status = main(
        [
            "verify",
            *_base_args(
                package_root=package_root,
                spec_path=spec_path,
                clean_evidence_root=clean_evidence_root,
                score_path=score_path,
                finalization_path=finalization_path,
                dossier_path=dossier_path,
                decision_path=decision_path,
                admission_path=admission_path,
                shadow_evidence_root=shadow_evidence_root,
            ),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "verify"
    assert payload["closed_paper_trade_count"] == 0
    assert len(payload["shadow_evidence_state_digest"]) == 64
