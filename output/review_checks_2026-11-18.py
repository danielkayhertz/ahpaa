"""Review checks - AHPAA senate district map. From adversarial review 2026-11-18.

Run from the project root:  python output/review_checks_2026-11-18.py
Exits non-zero while any check fails. Supersedes output/review_checks.py, whose
EXPECTED_PAIRS=1793 and Aurora=5 would fail a correctly fixed pipeline (see
adversarial-review-2026-11-18.md, F5).

Uses only output files (no geometry), so it runs in seconds. The expected
values come from an independent overlay of the raw shapefiles on 2026-11-18.
"""

import csv
import json
import re
import sys
from collections import defaultdict

CROSSWALK = "output/crosswalk.csv"
SPURIOUS = "output/spurious_review.csv"
UNMATCHED = "output/unmatched_places.csv"
DASH_JS = "output/dashboard_data.js"
DASH_HTML = "dashboard.html"

# Corrected rule (is_spurious = is_micro): 1,671 pairs over 1,288 matched
# municipalities. Fixing the 5 unmatched City/Village names (F6) adds a few.
PAIRS_MIN, PAIRS_MAX = 1666, 1700
MUNIS_MIN = 1288

# Exact district sets from the independent recompute (>=1 ha or >=0.5% of muni).
EXPECTED = {
    "Joliet": {19, 38, 40, 43, 49},
    "Aurora": {21, 25, 42, 49},
    "Springfield": {48, 54},
    "Rockford": {34, 35, 45},
    "Elgin": {22, 25, 33, 35},
    "Bloomington": {44, 46, 53},
    "Naperville": {21, 24, 25, 41, 42, 43, 49},
    "Chicago": {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
                18, 20, 28, 39},
}


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    fails = []
    cw = load(CROSSWALK)
    sp = load(SPURIOUS)
    dists = defaultdict(set)
    for r in cw:
        dists[(r["municipality_name"], r["county"])].add(int(float(r["senate_district"])))
    by_name = defaultdict(set)
    for (n, _), ds in dists.items():
        by_name[n] |= ds

    # F1 - no overlap >= 1 ha may be discarded (micro rule is area < 1 ha AND pct < 0.5)
    lost = [r for r in sp if float(r["overlap_area_m2"]) >= 10_000
            or float(r["overlap_pct_of_smaller"]) >= 0.5]
    if lost:
        fails.append(f"F1: {len(lost)} non-micro overlaps sit in {SPURIOUS} instead "
                     f"of the crosswalk, e.g. " + ", ".join(
                         f"{r['municipality_name']}-{r['senate_district']}" for r in lost[:4]))

    # F1 - every municipality's largest-overlap district must be in the map
    area = defaultdict(dict)
    for r in cw + sp:
        k = (r["municipality_name"], r["county"])
        area[k][int(float(r["senate_district"]))] = float(r["overlap_area_m2"])
    nopri = [k[0] for k, d in area.items() if max(d, key=d.get) not in dists.get(k, set())]
    if nopri:
        fails.append(f"F1: {len(nopri)} municipalities are missing their primary "
                     f"district, e.g. {nopri[:5]}")

    # F1 - named cities
    for name, want in EXPECTED.items():
        got = by_name.get(name, set())
        if got != want:
            fails.append(f"F1: {name} districts {sorted(got)}; expected {sorted(want)}")

    # F1 - totals
    if not PAIRS_MIN <= len(cw) <= PAIRS_MAX:
        fails.append(f"F1: crosswalk has {len(cw)} pairs; expected {PAIRS_MIN}-{PAIRS_MAX}")
    if len(dists) < MUNIS_MIN:
        fails.append(f"F1: {len(dists)} municipalities in crosswalk; expected >= {MUNIS_MIN}")

    # Dashboard data
    t = open(DASH_JS, encoding="utf-8").read()
    data = json.loads(t[t.index("{"):t.rindex("}") + 1])
    feats = [f["properties"] for f in data["municipalities"]["features"]]

    none = [p["municipality_name"] for p in feats if not p["senate_districts"]]
    if none:
        fails.append(f"F1: {len(none)} map features have no district "
                     f"(popup 'none in crosswalk'), e.g. {none[:5]}")
    j = [p for p in feats if p["municipality_name"] == "Joliet"]
    if not j or not {"43", "49"} <= set(j[0]["senate_districts"]):
        fails.append(f"F1: Joliet popup lists {j[0]['senate_districts'] if j else None}; "
                     f"must include 43 and 49")

    # F3 - exempt-by-population places must not be labelled 10-25%
    mis = [p["municipality_name"] for p in feats
           if p["bucket"] == "affordable-low" and p["affordable_housing_share"] < 0.10]
    if mis:
        fails.append(f"F3: {mis} have share < 10% but are bucketed 'Affordable 10-25%'")

    # H - district lists in numeric order
    unsorted = [p["municipality_name"] for p in feats
                if p["senate_districts"] != sorted(p["senate_districts"], key=int)]
    if unsorted:
        fails.append(f"H: {len(unsorted)} popups list districts in string order, "
                     f"e.g. {unsorted[:3]}")

    # Dashboard HTML
    h = open(DASH_HTML, encoding="utf-8").read()
    if re.search(r"totalMunis\s*\+=\s*filtered\.length", h):
        fails.append("F2: 'By District' adds pairs to totalMunis and labels them "
                     "'municipalities' (1,590 shown vs 1,254 distinct)")
    if "Planning and Accountability Act" in h:
        fails.append("H: header names the 'Planning and Accountability Act'; "
                     "statute is the Affordable Housing Planning and Appeal Act")
    if "micro-overlap(s) flagged" in h and lost:
        fails.append("H: footer calls all excluded overlaps 'micro-overlap(s)'")

    # F6 (carried from 2026-08-02) - suffix-disambiguated names
    um = {r["Place"] for r in load(UNMATCHED)}
    suf = sorted(p for p in um if p.rsplit(" ", 1)[-1] in ("City", "Village"))
    if suf:
        fails.append(f"F6: {suf} unmatched (IHDA City/Village disambiguator)")

    print("\n".join(f"  !! {f}" for f in fails) or "all checks pass")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
