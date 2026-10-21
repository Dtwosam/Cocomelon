"""Offline, count-only analysis of a bounded manually retrieved notice cohort.

No network, price, return, execution, strategy or source-admission operations.
Run from this audit directory with Python 3.11+; reads the two evidence JSONs.
"""

import csv
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 21, tzinfo=UTC)
KNOWN_AMENDMENTS = {
    "aa1d165426df4a7a84a0005a5a2f1e03",
    "a32a2a0e5132427ba568feb2b1a5c7ec",
}
PLAN_MODIFICATION = "fdb068f493444efba6cc979dec9a3955"
ROOT_BODY_CONFIRMATIONS = {
    "390301281fa84012b654ddbe811f9a53",
    "1f12c2c6cc2b43aa941e382dfc19c417",
}


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def dump(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def write_csv(name, rows):
    with (ROOT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize():
    records = []
    for year in (2025, 2026):
        for n in json.loads((ROOT / f"official-notices-{year}.json").read_text())["notices"]:
            if year == 2025:
                groups = [
                    {
                        "T": g["effective_start_utc"],
                        "rows": [
                            {
                                "asset": r["asset_label"],
                                "before": r["before_pct"],
                                "after": r["after_pct"],
                                "delta_pp": r["delta_percentage_points"],
                                "known_excluded": bool(r.get("exclusion_flag")),
                            }
                            for r in g["rows"]
                        ],
                        "complete": g["table_rows_complete"],
                    }
                    for g in n["effective_groups"]
                ]
                body = n["source_evidence"] == "official_body_opened"
                scope_excluded = False
            else:
                groups = [
                    {
                        "T": n["announced_effective_start_utc"],
                        "rows": [
                            {
                                "asset": r["asset"],
                                "before": r["before_percent"],
                                "after": r["after_percent"],
                                "delta_pp": r["signed_delta_pp"],
                                "known_excluded": r["asset"] == "EURI",
                            }
                            for r in n["ordinary_pm_rows"]
                        ],
                        "complete": n["complete_ordinary_flat_table_recovered"] is True,
                    }
                ]
                body = (
                    any(
                        e["mode"] == "body_open" and not e["redirect_to_generic_index"]
                        for e in n["source_evidence"]
                    )
                    or n["article_id"] in ROOT_BODY_CONFIRMATIONS
                )
                scope_excluded = n["article_id"] == "2200ab5284594d8a8b8239326e3d1fff"
            rows = [r for g in groups for r in g["rows"]]
            for r in rows:
                assert Decimal(str(r["delta_pp"])) == Decimal(str(r["after"])) - Decimal(
                    str(r["before"])
                )
            material = [r for r in rows if abs(r["delta_pp"]) >= 10]
            signal = [r for r in material if not r["known_excluded"]]
            times = sorted({g["T"] for g in groups if g["T"] != "UNKNOWN"})
            material_times = sorted(
                {
                    g["T"]
                    for g in groups
                    if g["T"] != "UNKNOWN"
                    and any(abs(r["delta_pp"]) >= 10 and not r["known_excluded"] for r in g["rows"])
                }
            )
            future = bool(times) and all(dt(t) >= END for t in times)
            unknown_table = not scope_excluded and not all(g["complete"] for g in groups)
            # Every unknown table is allowed one potential batch, never invented rows.
            potential = not future and not scope_excluded and bool(signal or unknown_table)
            signs = {"LONG" if r["delta_pp"] > 0 else "SHORT" for r in signal}
            record = {
                "article_id": n["article_id"],
                "year": year,
                "canonical_url": n["canonical_url"],
                "body_confirmed": body,
                "groups": groups,
                "all_known_times": times,
                "material_times": material_times,
                "raw_flat_rows": len(rows),
                "raw_material_rows": len(material),
                "material_rows_after_known_class_exclusions": len(signal),
                "raw_material": bool(material),
                "unknown_table": unknown_table,
                "future": future,
                "wrong_product_only": scope_excluded,
                "known_material_amendment": n["article_id"] in KNOWN_AMENDMENTS,
                "plan_modification_original_diff_unknown": n["article_id"] == PLAN_MODIFICATION,
                "potential": potential and n["article_id"] not in KNOWN_AMENDMENTS,
                "available_directions": sorted(signs),
                "strict_qualification": "UNKNOWN",
                "verified_executable": False,
                "verified_underlying_native_eligible_markets": "UNKNOWN",
            }
            records.append(record)
    assert len({r["article_id"] for r in records}) == len(records)
    return records


def dates_for(r, expanded=False):
    times = r["material_times"]
    if expanded and r["unknown_table"]:
        times = r["all_known_times"]
    return [dt(t) for t in times]


def in_window(r, begin, end, expanded=False):
    # Optimistic event-count ceiling: a full scheduled entry/exit window fits.
    # Publication, T0 receipt, identity, eligibility and actual fills still UNKNOWN.
    return any(
        begin <= t - timedelta(hours=6) and t + timedelta(hours=6) <= end
        for t in dates_for(r, expanded)
    )


def window_directions(r, begin, end):
    return {
        "LONG" if row["delta_pp"] > 0 else "SHORT"
        for g in r["groups"]
        if g["T"] != "UNKNOWN"
        and begin <= dt(g["T"]) - timedelta(hours=6)
        and dt(g["T"]) + timedelta(hours=6) <= end
        for row in g["rows"]
        if abs(row["delta_pp"]) >= 10 and not row["known_excluded"]
    }


def components(records):
    # Same article is one node, even when multiple effective groups are days apart.
    parents = list(range(len(records)))

    def find(x):
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    for i, a in enumerate(records):
        for j, b in enumerate(records[:i]):
            if any(abs(x - y) <= timedelta(hours=12) for x in dates_for(a) for y in dates_for(b)):
                parents[find(i)] = find(j)
    grouped = {}
    for i, r in enumerate(records):
        grouped.setdefault(find(i), []).append(r["article_id"])
    return list(grouped.values())


def analyze(records):
    occurred = [r for r in records if not r["future"]]
    raw = [r for r in occurred if r["raw_material"]]
    definite_veto_survivors = [r for r in raw if not r["known_material_amendment"]]
    # Reserve the disclosed Sep25plan modification from the narrower subtotal;
    # its original semantic diff is UNKNOWN, so retain it in the widest ceiling.
    material = [
        r for r in definite_veto_survivors if not r["plan_modification_original_diff_unknown"]
    ]
    potential = [r for r in records if r["potential"]]
    unplaced = [r for r in potential if not dates_for(r, True)]
    monthly = []
    for year in (2025, 2026):
        for month in range(1, 13 if year == 2025 else 11):
            key = f"{year}-{month:02d}"
            # Descriptive allocation only. Rolling ceilings use any T, once/article.
            a = [r for r in raw if min(r["material_times"]).startswith(key)]
            b = [r for r in material if min(r["material_times"]).startswith(key)]
            c = [
                r
                for r in potential
                if dates_for(r, True) and min(dates_for(r, True)).strftime("%Y-%m") == key
            ]
            directions = Counter("+".join(r["available_directions"]) for r in a)
            monthly.append(
                {
                    "month": key,
                    "observed_material_batches": len(a),
                    "revision_screened_material_batches": len(b),
                    "potential_cohort_ceiling_dated": len(c),
                    "long_only": directions["LONG"],
                    "short_only": directions["SHORT"],
                    "both_available_not_two_trades": directions["LONG+SHORT"],
                    "archive_census": "UNKNOWN",
                    "verified_executable_entries": 0,
                }
            )
    rolling = []
    summaries = {}
    for days in (90, 180):
        end = START + timedelta(days=days)
        windows = []
        while end <= END:
            begin = end - timedelta(days=days)
            a = [r for r in raw if in_window(r, begin, end)]
            b = [r for r in material if in_window(r, begin, end)]
            c = [r for r in potential if in_window(r, begin, end, True)]
            # Undated2026candidate cannot be assigned an invented T. Allow it at
            # most once as an extra slack term in any window intersecting2026.
            slack = sum(
                r["year"] == 2026 and end.year >= 2026 and end > datetime(2026, 1, 1, tzinfo=UTC)
                for r in unplaced
            )
            # One descriptive scheduled-entry assignment per batch, never one
            # count in each of two thirds. Actualfirstfill/side remain UNKNOWN.
            first_entries = [
                min(
                    t - timedelta(hours=6)
                    for t in dates_for(r)
                    if begin <= t - timedelta(hours=6) and t + timedelta(hours=6) <= end
                )
                for r in b
            ]
            thirds = []
            for third in range(3):
                lo = begin + timedelta(days=days * third / 3)
                hi = begin + timedelta(days=days * (third + 1) / 3)
                thirds.append(sum(lo <= entry < hi for entry in first_entries))
            assert sum(thirds) == len(b)
            long_available = sum("LONG" in window_directions(r, begin, end) for r in b)
            short_available = sum("SHORT" in window_directions(r, begin, end) for r in b)
            row = {
                "days": days,
                "start_utc": begin.isoformat(),
                "end_utc_exclusive": end.isoformat(),
                "observed_material_batches": len(a),
                "revision_screened_material_batches": len(b),
                "potential_dated_ceiling": len(c),
                "undated_slack_ceiling": slack,
                "potential_expanded_ceiling": len(c) + slack,
                "known_material_cohort_long_available": long_available,
                "known_material_cohort_short_available": short_available,
                "third_1_material": thirds[0],
                "third_2_material": thirds[1],
                "third_3_material": thirds[2],
                "scheduled_proxy_count_side_third_necessary_checks_only": (
                    len(b) >= 20
                    and long_available >= 5
                    and short_available >= 5
                    and min(thirds) >= 5
                ),
            }
            windows.append(row)
            end += timedelta(days=1)
        rolling.extend(windows)
        summaries[str(days)] = {
            "windows": len(windows),
            "raw_range": [
                min(w["observed_material_batches"] for w in windows),
                max(w["observed_material_batches"] for w in windows),
            ],
            "revision_screened_range": [
                min(w["revision_screened_material_batches"] for w in windows),
                max(w["revision_screened_material_batches"] for w in windows),
            ],
            "expanded_ceiling_range": [
                min(w["potential_expanded_ceiling"] for w in windows),
                max(w["potential_expanded_ceiling"] for w in windows),
            ],
            "max_expanded_examples": [
                w
                for w in windows
                if w["potential_expanded_ceiling"]
                == max(v["potential_expanded_ceiling"] for v in windows)
            ][:1],
            "raw_max_examples": [
                w
                for w in windows
                if w["observed_material_batches"]
                == max(v["observed_material_batches"] for v in windows)
            ][:1],
            "scheduled_proxy_necessary_check_windows_not_admitted_trials": sum(
                w["scheduled_proxy_count_side_third_necessary_checks_only"] for w in windows
            ),
            "latest": windows[-1],
        }
    labels = {
        r["asset"] for n in raw for g in n["groups"] for r in g["rows"] if abs(r["delta_pp"]) >= 10
    }
    summary = {
        "schema": "cocomelon.collateral-opportunity-frequency.v1",
        "study_start_utc": START.isoformat(),
        "rolling_last_end_utc": END.isoformat(),
        "verdict": "INCONCLUSIVE — INSUFFICIENT AUTHENTIC EVENT EVIDENCE",
        "bounds_apply_only_to_inspected_candidate_cohort": True,
        "archive_census_complete": False,
        "candidate_ids": len(records),
        "body_confirmed": sum(r["body_confirmed"] for r in records),
        "future_only": sum(r["future"] for r in records),
        "observed_material_batches": len(raw),
        "body_confirmed_material_batches": sum(r["body_confirmed"] for r in raw),
        "occurred_flat_rows": sum(r["raw_flat_rows"] for r in occurred),
        "occurred_raw_material_rows": sum(r["raw_material_rows"] for r in occurred),
        "raw_material_rows_all_including_future": sum(r["raw_material_rows"] for r in records),
        "unknown_table_ids": [r["article_id"] for r in records if r["unknown_table"]],
        "known_material_amendment_ids": sorted(KNOWN_AMENDMENTS),
        "plan_modification_original_diff_unknown_id": PLAN_MODIFICATION,
        "after_definite_amendment_veto_batches": len(definite_veto_survivors),
        "revision_screened_material_batches": len(material),
        "optimistic_expanded_cohort_ceiling": len(potential),
        "undated_potential_ids": [r["article_id"] for r in unplaced],
        "verified_executable_entries": 0,
        "verified_historical_eligible_market_count": "UNKNOWN",
        "distinct_material_asset_labels_not_identity_or_eligible_markets": len(labels),
        "raw_component_count": len(components(raw)),
        "cross_article_overlapping_component_members": [g for g in components(raw) if len(g) > 1],
        "raw_available_direction_batches": dict(
            Counter("+".join(r["available_directions"]) for r in raw)
        ),
        "revision_screened_available_direction_batches": dict(
            Counter("+".join(r["available_directions"]) for r in material)
        ),
        "rolling": summaries,
    }
    dump("normalized-notices.json", records)
    dump("frequency-summary.json", summary)
    write_csv("monthly-counts.csv", monthly)
    write_csv("rolling-counts.csv", rolling)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    analyze(normalize())
