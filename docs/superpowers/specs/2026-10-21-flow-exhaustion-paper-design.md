# Exploratory flow exhaustion PAPER policy

The owner explicitly requests autonomous implementation of an economically reasoned, unproven PAPER experiment. This is a bounded new research policy with no production wiring; operational launch is conditional. Prior positive-return admission requirements are superseded for exploratory testing, not validation.

## Intent and scope

Learn from both winners and losers, compare three participant mechanisms, implement the selected temporary-pressure/visible-recovery policy, freeze rules before prospective outcomes, and use independently attributable paper execution if safely supported. No healthy ordinary-worker intervention, PR1392 activation, live trading, old-account reset or weakening of risk/source gates.

## Design

Implement one pure policy accepting original ordered normalized native-mainnet trade and L2 events, explicit coverage qualification, ordinary eligibility and current hourly funding. Derive price/flow/depth conditions directly from those events, returning a StrategyDecision plus immutable target/stop/expiry/cost plan and evidence digest. Completeness is an externally authenticated input obligation: a caller flag or digest alone never authenticates venue coverage. Reject invalid/missing/future/stale/duplicate/out-of-order observations; do not repair or sort clocks. Provide pure conservative sizing and stop/target/time exit helpers. No external calls, orders or production imports.

The authoritative parameter and trial freeze is research/experiments/flow-exhaustion-v1/protocol.json, SHA256 c248746bbe4cd36fa63233b32bd643e368f2d20c63b0e973cf39ffd515873057. The entire protocol, including controls and evaluation, is frozen before new outcome collection. Synthetic fixtures test logic only. No calibrated expected return is asserted.

## Integration and acceptance

Tests cover mirrored LONG/SHORT, failure of every mechanism leg, original receipt and exchange clocks, duplicate identities, stale/missing/crossed books, incomplete tape, cost/risk constraints and exit priority. Run local full CI-equivalent checks, exact-head GitHub test/research CI before merge, then verify main. The existing pipeline/risk/paper adapter remains the future integration seam; there is no safe independent launcher today. No activation/PnL claims follow from code. A later launcher must establish custody, equal-capital NO_TRADE ledger, original source, resource isolation and unchanged risk/execution before launch, without requiring proven alpha.
