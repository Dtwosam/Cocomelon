from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.normalize import normalize_perp_dexs


class PublicFixtureReader(Protocol):
    def perp_dexs(self) -> object: ...

    def meta_and_asset_ctxs(self, dex: str = "") -> object: ...

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object: ...

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object: ...


def _sample_meta_and_contexts(raw: object, sample_size: int) -> object:
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError("metaAndAssetCtxs fixture must be a two-element array")
    meta_raw, contexts_raw = raw
    if not isinstance(meta_raw, dict) or not isinstance(contexts_raw, list):
        raise ValueError("metaAndAssetCtxs fixture has invalid shape")
    universe_raw = meta_raw.get("universe")
    if not isinstance(universe_raw, list):
        raise ValueError("metaAndAssetCtxs metadata must contain universe array")
    if len(universe_raw) != len(contexts_raw):
        raise ValueError("metaAndAssetCtxs universe/context lengths must match")

    meta = cast(dict[str, object], meta_raw).copy()
    meta["universe"] = universe_raw[:sample_size]
    return [meta, contexts_raw[:sample_size]]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def capture_public_fixtures(
    client: PublicFixtureReader,
    output_dir: Path,
    *,
    now_ms: int,
    sample_size: int = 3,
) -> Mapping[str, object]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)

    perp_dexs_raw = client.perp_dexs()
    dexes = normalize_perp_dexs(perp_dexs_raw)
    main_meta_raw = client.meta_and_asset_ctxs("")
    hip3_dex = dexes[0].name if dexes else None
    hip3_meta_raw = (
        client.meta_and_asset_ctxs(hip3_dex)
        if hip3_dex is not None
        else [{"universe": []}, []]
    )

    btc = MarketId(dex="", coin="BTC")
    candles_raw = client.candles(
        btc,
        "15m",
        start_ms=now_ms - (6 * 60 * 60 * 1000),
        end_ms=now_ms,
    )
    funding_raw = client.funding_history(
        btc,
        start_ms=now_ms - (72 * 60 * 60 * 1000),
        end_ms=now_ms,
    )

    files: dict[str, object] = {
        "perp_dexs.json": perp_dexs_raw,
        "meta_and_asset_ctxs_main.json": _sample_meta_and_contexts(main_meta_raw, sample_size),
        "meta_and_asset_ctxs_hip3.json": _sample_meta_and_contexts(hip3_meta_raw, sample_size),
        "candles_btc_15m.json": candles_raw,
        "funding_btc.json": funding_raw,
    }
    for name, payload in files.items():
        _write_json(output_dir / name, payload)

    return {
        "captured_at_ms": now_ms,
        "source": "https://api.hyperliquid.xyz/info",
        "hip3_dex": hip3_dex,
        "sample_size": sample_size,
        "files": tuple(files),
    }
