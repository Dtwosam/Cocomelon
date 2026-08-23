# Cocomelon

Cocomelon is an autonomous Hyperliquid perpetual-futures trading system designed to scan the real Hyperliquid mainnet market, identify intraday opportunities, paper-trade them against live market data, learn from validated results, and eventually execute tightly risk-controlled live trades.

The objective is not to maximize trade count or leverage. The objective is to discover and preserve positive net expectancy after fees, funding, slippage, and realistic execution costs while keeping drawdown and probability of ruin low.

## Non-negotiable project rules

- Hyperliquid **mainnet market data only**. Hyperliquid testnet is not used at any stage.
- Paper/shadow execution is the default until explicit live-promotion gates pass.
- Python is the primary language. Solidity is not part of V1 unless a real HyperEVM smart-contract requirement appears later.
- Initial data and infrastructure should use free/public sources and open-source libraries. Paid data/infrastructure is not a dependency without explicit approval.
- The risk engine has veto power over every strategy and model.
- No martingale, averaging down, unlimited leverage, trading without a stop, or silent live-mode activation.
- Historical order-book behavior must never be fabricated. Microstructure strategies are evaluated only on data actually collected or otherwise obtained with trustworthy provenance.

## Read first

1. [`AGENTS.md`](AGENTS.md) — rules every coding agent/chat must obey.
2. [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — canonical product and architecture specification.
3. [`docs/DECISIONS.md`](docs/DECISIONS.md) — locked architectural/product decisions and rationale.
4. [`docs/BUILD_ORDER.md`](docs/BUILD_ORDER.md) — phase-by-phase build order and promotion rules.
5. [`docs/STATUS.md`](docs/STATUS.md) — current repo state, active phase, and exact next step.
6. [`docs/CHATGPT_PROJECT_SOURCE.md`](docs/CHATGPT_PROJECT_SOURCE.md) — self-contained bootstrap context intended for ChatGPT Project Sources.

Detailed phase implementation plans live under `docs/superpowers/plans/`.

## Current status

Phase 0 — governance and source-of-truth documentation — is being established. See `docs/STATUS.md` for the live status.

## Important

No design, backtest, paper result, or model can guarantee profit. Cocomelon must earn the right to trade real capital through reproducible evidence and hard risk controls.