# Bounded collateral opportunity-frequency audit

**INCONCLUSIVE — INSUFFICIENT AUTHENTIC EVENT EVIDENCE.** Counts only; no
prices/returns, source admission, strategy change or trading implementation.
[Complete findings](../../../docs/collateral_opportunity_frequency_2026_10_21.md).

- [2025 official-record evidence projection](official-notices-2025.json)
- [2026 official-record evidence projection](official-notices-2026.json)
- [Normalized notice batches](normalized-notices.json)
- [Summary and explicit inspected-cohort ceilings](frequency-summary.json)
- [Monthly counts](monthly-counts.csv)
- [All1,048 rolling90/180-day windows](rolling-counts.csv)
- [One bounded archive attempt](archive-attempt.json)
- [Authenticated account extract](account-snapshot.json)
- [Replacement input/frequency assessment](replacement-evidence.md)
- [Independent calculation review](review.md)
- [Report and decision review](report-review.md)
- [Later native ticker-spelling proxy, never eligibility](native-ticker-proxy.json)
- [File hashes](manifest.sha256)

Reproduce offline with `python3 analyze.py` from this directory (Python3.11+;
stdlib only). This reads the two saved evidence projections and rewrites the
normalized JSON, summary and count CSVs. It has no network or execution imports.
It is a one-study analysis, not a notice collector or source monitor. No test
fixtures or generated dates are represented as real observations.

The evidence JSONs are manually transcribed facts from official current bodies
or official-domain indexed text, not raw HTTP responses, original notice bytes,
complete archive pages, authenticated historic vintages or receipt logs. Every
record retains its canonical URL, displayed publication/update text, explicit
effective UTC where recovered, product/table scope, ratios, source mode and gaps.
Internal web-tool reference IDs were removed. No historical bot first receipt
exists. Unstated publication timezone remains UNKNOWN.

Two root spot-checks subsequently opened complete current English bodies for
`1f12c2c6cc2b43aa941e382dfc19c417` (Sep04:12ordinary rows) and
`390301281fa84012b654ddbe811f9a53` (Sep18:9ordinary rows). These upgrades are
explicit constants in the normalization; the earlier2026 evidence projection
retains the original indexed-only observation. December12's root spot-check
duplicates an already body-confirmed2025 record. No duplicate article is counted.
Together there are21unique body-confirmed articles,18 historical material.

Counts distinguish421historical material asset rows,52article batches,
49revision-screened material candidates,54widest potential batches within the
found cohort, and0verified executable entries. Two definite2025amendments are
vetoed. A disclosed2026plan modification with unknown original diff is reserved
from the narrower subtotal and retained only in the widest potential ceiling.
Four missing tables/date records can add one batch each, never invented rows.
One announcedOct23event is future-only. WBETH/EURI rows do not contribute to side
availability; all remaining underlying/class/market identities are unverified.

Monthly allocation is earliest material T per article. Rolling windows count an
article once if ANY relevant effective group has its full[T−6h,T+6h] inside the
window. Endpoints are UTC midnight; end label is exclusive for entries, while a
scheduled exit exactly at end is allowed in this optimistic timing ceiling.
Direction availability uses only groups in that window. Each article receives
one earliest in-window scheduled-entry third assignment, never two counts across
thirds. Actual first fill and selected side remain UNKNOWN. The necessary-check
flag is only a scheduling proxy and cannot establish trial eligibility. SharedT
or overlapping12h windows across articles are unioned for formal component
counts; no such overlaps were found among recovered material groups. Separation
does not prove causal/statistical independence.

The one undated2026candidate is not assigned its title date. It adds at most one
explicit slack term to an expanded rolling ceiling intersecting2026. The54total
and rolling12/22maxima bound only found records under favorable assumptions.
They do not bound omitted notices or establish a future rate. Every month's
archive completeness, including zero-observed November2025, remains UNKNOWN.

No original protocol bytes, ordinary worker, account, runtime code, workflow or
policy freeze was changed. No fill, net return, profitability or new economic
progress is inferred from the audit or its software verification. LIVE OFF.

Validation: independent recomputation of all1,048 rolling rows and the two source
cohorts;15existing profitability-handoff tests PASS; Ruff check/format PASS for
the offline analysis; JSON/CSV arithmetic and relative report links PASS. Both
original protocol file hashes match their frozen SHA256 exactly. No new runtime
test or economic outcome is implied.
