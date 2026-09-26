from __future__ import annotations

import json
import os
import subprocess
import sys

SCRIPT = "scripts/render_universe_opportunity_diagnostics.py"


def test_universe_diagnostics_renderer_marks_report_non_economic(tmp_path) -> None:
    payload = {
        "observed_at_ms": 1_700_000_000_000,
        "dex_count": 2,
        "market_count": 100,
        "rankable_count": 30,
        "native_rankable_count": 20,
        "hip3_rankable_count": 10,
        "current_native_deep_limit": 20,
        "hip3_in_combined_top_n": 3,
        "combined_top_n": [
            {
                "market": "xyz:ABC",
                "dex": "xyz",
                "ordinal": 1,
                "score": "0.9",
                "reason_codes": ["ELIGIBLE"],
            }
        ],
        "current_native_top_n": [],
        "top_hip3": [
            {
                "market": "xyz:ABC",
                "dex": "xyz",
                "ordinal": 1,
                "score": "0.9",
                "reason_codes": ["ELIGIBLE"],
            }
        ],
        "native_only_top_n_absent_from_combined": ["ETH"],
        "paper_trading_policy": "native_only",
        "economic_authority": False,
        "live_orders": False,
    }
    source = tmp_path / "diagnostics.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, SCRIPT, "--input", str(source)],
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )

    output = completed.stdout
    assert "DIAGNOSTICS ONLY" in output
    assert "native_only" in output
    assert "HIP-3 markets in combined top-20" in output
    assert "`3`" in output
    assert "xyz:ABC" in output
    assert "`ETH`" in output
    assert "not a direct HIP-3 displacement count" in output
    assert "does not change trading eligibility" in output
