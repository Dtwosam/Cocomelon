# Cocomelon

Cocomelon is an autonomous Hyperliquid perpetual-futures trading system designed to scan the real Hyperliquid mainnet market, identify intraday opportunities, paper-trade them against live market data, learn from validated results, and eventually execute tightly risk-controlled live trades.

The objective is not to maximize trade count or leverage. The objective is to discover and preserve positive net expectancy after fees, funding, slippage, and realistic execution costs while keeping drawdown and probability of ruin low.

## START HERE — Profitability first (2026-10-10)

**The trader is running but is not yet profitable.** At the last verified mainnet-paper heartbeat (2026-10-09 23:40 UTC, GitHub Issue #469), the account had **155 closed simulated trades, $9,682.45 in equity, -$317.55 total net PnL (-3.18%)**. These are a historical snapshot, not a live quote. Real-money orders are **DISABLED**.

**Read [`docs/PROFITABILITY_PRIORITY.md`](docs/PROFITABILITY_PRIORITY.md) FIRST.** It contains the standing user instruction to work autonomously toward after-cost profitability, the latest verified economic baseline, the frozen SHORT-rank and paired-account research priorities, the evidence defects to fix and the exact next-chat workflow. Never treat a completed PR or hypothetical skipped loss as proof of profitable trading.

## Non-negotiable project rules

- Hyperliquid **mainnet market data only**. Hyperliquid testnet is not used at any stage.
- Paper/shadow execution is the default until explicit live-promotion gates pass.
- Python is the primary language. Solidity is not part of V1 unless a real HyperEVM smart-contract requirement appears later.
- Initial data and infrastructure should use free/public sources and open-source libraries. Paid data/infrastructure is not a dependency without explicit approval.
- The risk engine has veto power over every strategy and model.
- No martingale, averaging down, unlimited leverage, trading without a stop, or silent live-mode activation.
- Historical order-book behavior must never be fabricated. Microstructure strategies are evaluated only on data actually collected or otherwise obtained with trustworthy provenance.

## Read first

1. [`docs/PROFITABILITY_PRIORITY.md`](docs/PROFITABILITY_PRIORITY.md) — **read first: current money-first mandate, evidence and next actions**.
2. [`AGENTS.md`](AGENTS.md) — rules every coding agent/chat must obey.
3. [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — canonical product and architecture specification.
4. [`docs/DECISIONS.md`](docs/DECISIONS.md) — locked architectural/product decisions and rationale.
5. [`docs/BUILD_ORDER.md`](docs/BUILD_ORDER.md) — phase-by-phase build order and promotion rules.
6. [`docs/STATUS.md`](docs/STATUS.md) — current repo state, active phase, and exact next step.
7. [`docs/CHATGPT_PROJECT_SOURCE.md`](docs/CHATGPT_PROJECT_SOURCE.md) — self-contained bootstrap context intended for ChatGPT Project Sources.

Detailed phase implementation plans live under `docs/superpowers/plans/`.

## Current status

Phases 0–9 established the engineering and research foundation; Phase 10 historical-learning and continuous mainnet-paper operations are active. The economic baseline is **negative**; live/promotion are blocked. The top of `docs/STATUS.md` and `docs/PROFITABILITY_PRIORITY.md` describe the latest verified work, and GitHub Issue #469 is the live paper heartbeat. Do not mistake old historical phase notes for today's status.

## Important

No design, backtest, paper result, or model can guarantee profit. Cocomelon must earn the right to trade real capital through reproducible evidence and hard risk controls.