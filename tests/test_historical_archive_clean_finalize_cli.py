from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_clean_finalize_cli as cli


def test_finalization_cli_is_offline_and_emits_terminal_verdict(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    runtime = SimpleNamespace(
        spec=SimpleNamespace(),
    )
    pinned = SimpleNamespace(
        runtime=runtime,
        bundle=SimpleNamespace(runtime_id="7" * 64),
        pin=SimpleNamespace(pin_id="8" * 64),
    )
    checkpoint = SimpleNamespace()
    block = SimpleNamespace(
        to_dict=lambda: {
            "block_index": 0,
            "settled_trade_count": 20,
            "long_trade_count": 10,
            "short_trade_count": 10,
            "gross_return_sum": "0.22",
            "modeled_cost_sum": "0.02",
            "net_return_sum": "0.20",
            "mean_net_return": "0.01",
            "min_required_trades": 15,
            "min_required_mean_net_return": "0",
            "passes_trade_floor": True,
            "passes_mean_floor": True,
        }
    )
    finalization = SimpleNamespace(
        paper_only=True,
        prospective_only=True,
        promotion_eligible=False,
        execution_ready=False,
        candidate_id="a" * 64,
        model_artifact_id="d" * 64,
        validation_spec_id="e" * 64,
        campaign_id="f" * 64,
        runtime_id="7" * 64,
        pin_id="8" * 64,
        checkpoint_id="9" * 64,
        finalization_id="1" * 64,
        finalized_at_ms=123,
        verdict="eligible_for_candidate_review",
        eligible_for_candidate_review=True,
        reason_codes=(),
        capture_coverage=Decimal("0.95"),
        captured_anchor_count=95,
        expected_anchor_count=100,
        settled_trade_count=80,
        mean_net_return=Decimal("0.01"),
        block_results=(block,),
    )
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(
        cli,
        "load_archive_clean_operational_checkpoint",
        lambda *args, **kwargs: checkpoint,
    )
    monkeypatch.setattr(
        cli,
        "build_archive_clean_finalization",
        lambda *args, **kwargs: finalization,
    )
    finalization_path = tmp_path / "terminal" / "finalization.json"
    monkeypatch.setattr(
        cli,
        "write_archive_clean_finalization",
        lambda *args, **kwargs: finalization_path,
    )

    payload = cli.archive_clean_finalization_payload(
        runtime_root=tmp_path / "runtime",
        pin_id="8" * 64,
        checkpoint_path=tmp_path / "checkpoint.json",
        output_root=tmp_path / "terminal",
        clock_ms=lambda: 123,
    )

    assert payload["command"] == "historical-archive-clean-finalize"
    assert payload["verdict"] == "eligible_for_candidate_review"
    assert payload["eligible_for_candidate_review"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["mean_net_return"] == "0.01"
    assert payload["finalization"] == str(finalization_path)

    status = cli.main(
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--pin-id",
            "8" * 64,
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--output-root",
            str(tmp_path / "terminal"),
        ]
    )
    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    emitted = json.loads(captured.out)
    assert emitted["paper_only"] is True
    assert emitted["prospective_only"] is True
    assert emitted["promotion_eligible"] is False
    assert emitted["execution_ready"] is False
