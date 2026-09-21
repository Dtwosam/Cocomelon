from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import cocomelon.historical_context_opportunity_cli as cli


def _args() -> list[str]:
    return [
        "--source-root",
        "sources",
        "--output-root",
        "out",
        "--market",
        "BTC",
        "--horizon-ms",
        "3600000",
        "--anchor-interval",
        "1h",
        "--round-trip-fee-fraction",
        "0.0007",
        "--round-trip-slippage-fraction",
        "0.0005",
        "--funding-reserve-fraction-per-hour",
        "0.0001",
        "--stability-blocks",
        "4",
        "--min-block-rows",
        "20",
    ]


def test_context_opportunity_parser_accepts_1h_lane() -> None:
    args = cli.build_parser().parse_args(_args())

    assert args.anchor_interval == "1h"
    assert args.stability_blocks == 4
    assert args.min_block_rows == 20


def test_context_opportunity_cli_emits_provenance_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opportunity_map = SimpleNamespace(
        entries=(
            SimpleNamespace(stable_long=True, stable_short=False),
            SimpleNamespace(stable_long=False, stable_short=True),
            SimpleNamespace(stable_long=False, stable_short=False),
        )
    )
    report = SimpleNamespace(
        report_id="a" * 64,
        dataset_id="b" * 64,
        evidence_class="touched_development",
        anchor_interval="1h",
        dataset_row_count=123,
        markets=("BTC",),
        horizons_ms=(3_600_000,),
        opportunity_map=opportunity_map,
    )
    monkeypatch.setattr(
        cli,
        "run_context_opportunity_from_sources",
        lambda **kwargs: report,
    )

    assert cli.main(_args()) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["report_id"] == "a" * 64
    assert payload["dataset_id"] == "b" * 64
    assert payload["evidence_class"] == "touched_development"
    assert payload["stable_long_count"] == 1
    assert payload["stable_short_count"] == 1
