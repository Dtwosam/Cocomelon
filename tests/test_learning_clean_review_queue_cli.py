from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.learning_clean_review_queue_cli import main
from tests.test_learning_clean_review_queue import _lineage


def test_learning_clean_review_queue_cli_renders_verified_queue(
    tmp_path,
    capsys,
) -> None:
    root = _lineage(
        tmp_path,
        values=[Decimal("0.1")] * 20,
        finalize=True,
    )

    status = main(
        [
            "--state-root",
            str(root),
            "--format",
            "json",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] == 1
    assert payload["review_ready_count"] == 1
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
