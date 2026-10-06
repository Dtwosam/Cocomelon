from __future__ import annotations

import json
from pathlib import Path

from cocomelon import frozen_no_trade_shadow_cli


def test_frozen_shadow_cli_emits_authority_negative_empty_shadow(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "forward.json"
    source.write_text(
        json.dumps(
            {
                "decision_state_digest": "a" * 64,
                "feature_state_digest": "b" * 64,
                "diagnostic_only": True,
                "hypothetical_pnl": False,
                "execution_authority": False,
                "schema_version": 2,
                "outcomes": [],
            }
        ),
        encoding="utf-8",
    )

    assert frozen_no_trade_shadow_cli.main(["--input", str(source)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"]["market"] == "MON"
    assert payload["candidate"]["direction"] == "short"
    assert payload["matching_labeled_outcomes"] == 0
    assert payload["evidence_class"] == "prospective_shadow"
    assert payload["prospective_only"] is True
    assert payload["review_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_authority"] is False
