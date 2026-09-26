from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _rows(raw: object, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be a list")
    rows: list[Mapping[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{field} entries must be objects")
        rows.append(item)
    return rows


def render_universe_diagnostics(payload: Mapping[str, Any]) -> str:
    observed_at_ms = int(payload["observed_at_ms"])
    observed = datetime.fromtimestamp(observed_at_ms / 1000, tz=UTC)
    combined = _rows(payload.get("combined_top_n"), "combined_top_n")
    hip3 = _rows(payload.get("top_hip3"), "top_hip3")
    displaced_raw = payload.get("displaced_native_markets", [])
    if not isinstance(displaced_raw, list):
        raise ValueError("displaced_native_markets must be a list")
    displaced = [str(item) for item in displaced_raw]

    lines = [
        "## Universe opportunity coverage",
        "",
        f"**Updated:** `{observed.isoformat()}`",
        "**Data:** `Hyperliquid mainnet public market data`",
        "**Authority:** `DIAGNOSTICS ONLY` · **Live orders:** `false`",
        "**Current paper-trading policy:** `native_only`",
        "",
        "### Coverage",
        "",
        f"- discovered HIP-3 DEXes: `{payload['dex_count']}`",
        f"- discovered perp markets: `{payload['market_count']}`",
        f"- rankable markets: `{payload['rankable_count']}`",
        f"- rankable native markets: `{payload['native_rankable_count']}`",
        f"- rankable HIP-3 markets: `{payload['hip3_rankable_count']}`",
        (
            "- HIP-3 markets in combined top-"
            f"{payload['current_native_deep_limit']}: "
            f"`{payload['hip3_in_combined_top_n']}`"
        ),
        "",
        "### Combined opportunity leaders",
        "",
    ]

    if combined:
        lines.extend(
            [
                "| Rank | Market | Namespace | Score | Reasons |",
                "| ---: | --- | --- | ---: | --- |",
            ]
        )
        for row in combined:
            reasons = row.get("reason_codes", [])
            reason_text = (
                ", ".join(str(item) for item in reasons)
                if isinstance(reasons, list)
                else ""
            )
            namespace = str(row.get("dex") or "native")
            lines.append(
                "| {rank} | {market} | {namespace} | {score} | {reasons} |".format(
                    rank=row["ordinal"],
                    market=row["market"],
                    namespace=namespace,
                    score=row["score"],
                    reasons=reason_text,
                )
            )
    else:
        lines.append("_No rankable markets in this observation._")

    lines.extend(["", "### Top HIP-3 opportunities", ""])
    if hip3:
        lines.extend(
            [
                "| Global rank | Market | DEX | Score | Reasons |",
                "| ---: | --- | --- | ---: | --- |",
            ]
        )
        for row in hip3:
            reasons = row.get("reason_codes", [])
            reason_text = (
                ", ".join(str(item) for item in reasons)
                if isinstance(reasons, list)
                else ""
            )
            lines.append(
                "| {rank} | {market} | {dex} | {score} | {reasons} |".format(
                    rank=row["ordinal"],
                    market=row["market"],
                    dex=row["dex"],
                    score=row["score"],
                    reasons=reason_text,
                )
            )
    else:
        lines.append("_No rankable HIP-3 markets in this observation._")

    lines.extend(["", "### Native markets displaced in a combined top-N", ""])
    if displaced:
        lines.append(", ".join(f"`{market}`" for market in displaced))
    else:
        lines.append("_None in this observation._")

    lines.extend(
        [
            "",
            (
                "> This report does not change trading eligibility. It measures "
                "what the existing coarse ranking would surface if native and "
                "HIP-3 markets were compared together."
            ),
            "",
            "<details><summary>Full diagnostics JSON</summary>",
            "",
            "```json",
            json.dumps(dict(payload), indent=2, sort_keys=True),
            "```",
            "</details>",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render-universe-opportunity-diagnostics"
    )
    parser.add_argument("--input", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    raw: object = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("diagnostics payload must be an object")
    print(render_universe_diagnostics(raw), end="")


if __name__ == "__main__":
    main()
