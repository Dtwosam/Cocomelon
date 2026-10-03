from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_long_trend_carveout_execution_shadow import (
    ProspectiveLongTrendExecutionShadowError,
    evaluate_long_trend_carveout_execution_shadow,
)
from cocomelon.research.prospective_long_trend_carveout_forward_markout_ledger import (
    ProspectiveLongTrendCarveoutLedgerError,
    load_long_trend_carveout_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-long-trend-execution-shadow",
        description=(
            "Evaluate the research-only LONG+trend entry execution shadow "
            "behind the durable fast-markout readiness gate."
        ),
    )
    parser.add_argument("source_path", type=Path)
    parser.add_argument("gate_ledger_path", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def _load_json(path: Path, *, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveLongTrendExecutionShadowError(
            f"{label} is invalid"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = _load_json(
            args.source_path,
            label="LONG+trend execution-shadow source",
        )
        gate = load_long_trend_carveout_ledger(
            args.gate_ledger_path
        )
        summary = gate.get("summary")
        if not isinstance(summary, dict):
            raise ProspectiveLongTrendExecutionShadowError(
                "LONG+trend gate summary is missing"
            )
        gate_ready = (
            summary.get(
                "all_horizons_ready_for_execution_shadow_investigation"
            )
            is True
        )
        gate_digest = gate.get("ledger_sha256")
        if not isinstance(gate_digest, str):
            raise ProspectiveLongTrendExecutionShadowError(
                "LONG+trend gate digest is missing"
            )
        result = evaluate_long_trend_carveout_execution_shadow(
            source,
            durable_gate_ready=gate_ready,
            durable_gate_ledger_sha256=gate_digest,
        )
    except (
        ProspectiveLongTrendExecutionShadowError,
        ProspectiveLongTrendCarveoutLedgerError,
    ) as exc:
        raise SystemExit(str(exc)) from exc

    args.json_out.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "durable_gate_ready": result[
                    "durable_gate_ready"
                ],
                "source_opportunity_count": result[
                    "source_opportunity_count"
                ],
                "evaluated": result["evaluated"],
                "execution_authority": result[
                    "execution_authority"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
