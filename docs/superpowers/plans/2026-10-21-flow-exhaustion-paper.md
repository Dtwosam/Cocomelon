# Frozen flow exhaustion policy implementation plan

Owner execution method: execute autonomously now; parallel economic and safety reviews, native implementation review. No routine approval pauses. Design: ../specs/2026-10-21-flow-exhaustion-paper-design.md.

- [x] Refresh Issue469, permanent1258mandate, main and active worker/job/head; preserve original checkout.
- [x] Read all321canonical trade outcomes and compare three economic mechanisms without fitting parameters.
- [x] Freeze protocol.json and design before viewing prospective outcomes.
- [x] Add tests/test_flow_exhaustion.py first; observe missing-module RED.
- [x] Implement src/cocomelon/research/flow_exhaustion.py: frozen input/plan types, evaluate_flow_exhaustion(...) -> FlowExhaustionPlan, quantity_for_plan(...) -> Decimal, exit_reason(...) -> str|None, all exactly matching protocol. NO_TRADE plans carry no stop/target. Preserve source order; explicit evidence digest and reasons. No runtime imports/wiring/network/account writes.
- [x] Independently review policy/protocol parity, invalid input handling, sizing and exit priority. Fix concrete findings and rerun tests.
- [ ] Run full compile/Ruff/mypy/pytest and research CI-equivalent command; preserve exact output and code SHA.
- [x] Update priority, decisions, status and portable bootstrap with explicit exploratory-versus-validation distinction, actual activation blocker and zero prospective results.
- [ ] Commit focused files, open PR, require exact-head test/research CI; merge safe research-only change if green, verify post-merge CI without restarting trader.

Review focus: original time regressions cannot be sorted away; same price-band visible recovery must not become static imbalance; book gaps/tape gaps remain disqualifying; sizing reserves costs and independent risk remains authoritative; protective stop precedes discretionary exit; no finite test fixture establishes authentic prospective returns.
