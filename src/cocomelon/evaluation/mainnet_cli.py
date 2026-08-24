from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.evaluation.aggregate import EvidenceAggregationResult
from cocomelon.evaluation.mainnet_aggregate import (
    aggregate_genuine_mainnet_evidence,
    corpus_attestation_path,
    validate_genuine_mainnet_corpus,
)


def _result_payload(
    result: EvidenceAggregationResult,
    *,
    journal: Path,
    facts: Path,
) -> dict[str, object]:
    return {
        "code_revision": result.code_revision,
        "run_ids": list(result.run_ids),
        "source_count": result.source_count,
        "trade_count": result.trade_count,
        "observation_count": result.observation_count,
        "decision_fact_count": result.decision_fact_count,
        "equity_fact_count": result.equity_fact_count,
        "journal": str(journal),
        "facts": str(facts),
        "corpus_attestation": str(corpus_attestation_path(journal)),
        "evidence_kind": "genuine_public_hyperliquid_mainnet",
        "network_access": False,
        "live_orders": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-mainnet-evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--journal", required=True, type=Path)
    aggregate.add_argument("--facts", required=True, type=Path)
    aggregate.add_argument("--source-root", required=True, action="append", type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--journal", required=True, type=Path)
    validate.add_argument("--facts", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "aggregate":
        result = aggregate_genuine_mainnet_evidence(
            args.journal,
            args.facts,
            tuple(args.source_root),
        )
    else:
        result = validate_genuine_mainnet_corpus(args.journal, args.facts)
    print(
        json.dumps(
            _result_payload(result, journal=args.journal, facts=args.facts),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
