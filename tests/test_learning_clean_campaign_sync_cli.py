from __future__ import annotations

import json

from cocomelon.learning_clean_campaign_sync_cli import main
from cocomelon.research import research_learning_sync
from tests.test_learning_clean_campaign_sync import _campaign, _kwargs
from tests.test_learning_clean_validation_score import _setup


def test_learning_clean_campaign_sync_cli_emits_non_economic_receipt(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    campaign, _snapshot_value, _trade_value, verified = _campaign(
        tmp_path,
        spec=spec,
    )
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: verified,
    )
    kwargs = _kwargs()

    status = main(
        [
            "--campaign-root",
            str(campaign),
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--evidence-root",
            str(evidence_root),
            "--upstream-run-id",
            str(kwargs["upstream_run_id"]),
            "--upstream-run-attempt",
            str(kwargs["upstream_run_attempt"]),
            "--upstream-head-sha",
            str(kwargs["upstream_head_sha"]),
            "--upstream-artifact-id",
            str(kwargs["upstream_artifact_id"]),
            "--upstream-artifact-digest",
            str(kwargs["upstream_artifact_digest"]),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-clean-campaign-sync"
    assert payload["source_trade_count"] == 1
    assert payload["clean_trade_prediction_count"] == 1
    assert payload["settled_outcome_count_after"] == 1
    assert payload["paper_only"] is True
    assert payload["research_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert "net_r" not in payload
    assert "predicted_net_r" not in payload
