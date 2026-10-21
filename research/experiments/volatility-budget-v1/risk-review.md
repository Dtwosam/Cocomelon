# Volatility PAPER lifecycle arithmetic review

Read-only review of current volatility_budget_paper.py and shared risk/IOC/accounting code. No operational test, historical return analysis, account creation or code edits performed.

No concrete risk-sizing, fee-double-counting or funding-cash arithmetic defect found in reviewed paths.

- Independent reserve is exactly59bp:25bp entry +25bp stop +9bp round-trip fee. Frozen scenario c<=50bp therefore cannot reduce it. quantity_for_plan uses max(c,59), risk request preserves the same buffer, with0.10% equity as the planned-risk ceiling.
- Lifecycle caps approved notional by independent approval and frozen quantity caps. Shared IOC recalculates stop loss plus retained buffer for EVERY actual visible-depth fill and clips quantity against remaining approved risk. Accounting independently rejects a committed opening above that ceiling. Actual gaps can exceed planned risk; no guarantee is implied.
- Stops/targets remain the frozen predecision E geometry; target positivity is checked by pure policy. Attempt-time risk uses actual executable quote and native independent stop/margin/liquidation checks. No policy retiming or target/stop reanchor observed.
-25bp IOC reference anchoring remains an interpretation acknowledged by the primary reviewer; no proven policy defect is asserted and no policy tuning requested.
- Existing defaults preserve1% daily loss,3% rolling weekly drawdown, three-loss/1h cooldown, aggregate/shared correlation risk and independent health vetoes. The9950 marked-equity permanent entry suspension is additional and protective exits do not call entry authorization.
- Cash subtracts actual taker fees once and uses actual fill prices for realized gross. Scenario spread/impact/funding reserves affect sizing only and are not booked as extra costs.
- Hour-boundary snapshots retain actual quantity before later reductions; settled funding is signed quantity*original oracle*rate with long/short sign reversal, persisted idempotently. Late post-close accrual updates cash and component net; unknown liabilities block entries/qualification. Loss-state refresh reclassifies late-funded completed components.

Limits: this is code review only and not original-source authentication, operational custody admission, source completeness evidence, test-suite certification or economic proof. Other reviewers own lifecycle/custody/source review. Full exact-head suite and CI remain pending with root.
