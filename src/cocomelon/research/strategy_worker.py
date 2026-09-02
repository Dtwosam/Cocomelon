from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_trusted_seam() -> ModuleType:
    path = Path("/trusted/strategy_seam.py")
    spec = importlib.util.spec_from_file_location("trusted_research_strategy_seam", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("trusted strategy seam could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    seam = _load_trusted_seam()
    try:
        payload: object = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        raise RuntimeError("candidate strategy input must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("candidate strategy input must be an object")
    context = seam.strategy_context_from_payload(payload.get("context"))

    from cocomelon.strategies.engine import evaluate_strategies

    decision = evaluate_strategies(context).decision
    encoded = json.dumps(
        seam.strategy_decision_to_payload(decision),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    sys.stdout.write(encoded + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
