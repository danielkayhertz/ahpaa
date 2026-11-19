"""Review checks - AHPAA crosswalk. From adversarial review 2026-08-02.

SUPERSEDED by output/review_checks_2026-11-18.py. This script's EXPECTED_PAIRS
(1793) and Aurora=5 count micro overlaps (<1 ha) as real, so it fails on a
correctly fixed pipeline. See adversarial-review-2026-11-18.md, F5.

Run from the project root:  python output/review_checks.py

Exits non-zero while any check fails. These are regression guards for the
findings in output/adversarial-review-2026-08-02.md, not a test of the
pipeline's correctness in general.
"""

import csv
import sys
from collections import defaultdict

CROSSWALK = "output/crosswalk.csv"
SPURIOUS = "output/spurious_review.csv"
UNMATCHED = "output/unmatched_places.csv"

# Municipalities that must never be absent from the crosswalk. Not exhaustive —
# a sample of the 34 that F2 found missing, weighted to the largest.
MUST_APPEAR = [
    "Springfield", "Belleville", "Danville", "Granite City",
    "Lockport", "Carbondale", "Macomb", "Mount Vernon",
]

# Independently re-derived pair count (R/sf and Python/geopandas agreed exactly).
# Every non-zero intersection, no filtering. See F3.
EXPECTED_PAIRS = 1793
PAIR_TOLERANCE = 5          # allow small drift from a TIGER/plan vintage change

# District counts from the same replications. See F3.
EXPECTED_DISTRICTS = {
    "Springfield": 2, "Aurora": 5, "Rockford": 3,
    "Joliet": 5, "Bloomington": 3, "Naperville": 7, "Chicago": 21,
}


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    fails = []

    cw = load(CROSSWALK)
    sp = load(SPURIOUS)
    by_muni = defaultdict(list)
    for r in cw:
        by_muni[r["municipality_name"]].append(r)

    # 1 - F2: municipalities must not vanish from the deliverable entirely
    for name in MUST_APPEAR:
        if name not in by_muni:
            fails.append(f"F2: {name!r} has no row in {CROSSWALK}")

    dropped = {r["municipality_name"] for r in sp} - set(by_muni)
    if dropped:
        fails.append(
            f"F2: {len(dropped)} municipalities appear only in {SPURIOUS} and "
            f"never in the crosswalk, e.g. {sorted(dropped)[:5]}"
        )

    # 2 - F1: no large overlap may be discarded on shape alone
    big = [r for r in sp
           if float(r["overlap_area_m2"]) > 1_000_000
           and "sliver" in r["flag_reason"]
           and "micro" not in r["flag_reason"]]
    if big:
        area = sum(float(r["overlap_area_m2"]) for r in big) / 1e6
        worst = max(big, key=lambda r: float(r["overlap_pct_of_smaller"]))
        fails.append(
            f"F1: {len(big)} overlaps larger than 1 km2 ({area:.0f} km2 total) "
            f"discarded by the compactness test alone; worst is "
            f"{worst['municipality_name']} district {worst['senate_district']} "
            f"at {float(worst['overlap_pct_of_smaller']):.1f}%"
        )

    # 3 - F3: pair count must match the independent replications
    if abs(len(cw) - EXPECTED_PAIRS) > PAIR_TOLERANCE:
        fails.append(
            f"F3: crosswalk has {len(cw)} pairs; two blind replications both "
            f"produced {EXPECTED_PAIRS} (tolerance {PAIR_TOLERANCE})"
        )

    # 4 - F3: per-municipality district counts
    for name, want in EXPECTED_DISTRICTS.items():
        got = len(by_muni.get(name, []))
        if got != want:
            fails.append(
                f"F3: {name} spans {want} senate districts per independent "
                f"replication; crosswalk has {got}"
            )

    # 5 - F4: the manual review column must be complete before publishing
    blank = [r for r in sp if not (r.get("Legit?") or "").strip()]
    if blank:
        fails.append(
            f"F4: {len(blank)} of {len(sp)} rows in {SPURIOUS} have an empty "
            f"'Legit?' column - the discard set has not been reviewed"
        )

    # 6 - F6: suffix-disambiguated names must not silently fail to match
    um = {r["Place"] for r in load(UNMATCHED)}
    suffixed = {p for p in um if p.rsplit(" ", 1)[-1] in ("City", "Village")}
    if suffixed:
        fails.append(
            f"F6: {sorted(suffixed)} unmatched - IHDA appends City/Village to "
            f"disambiguate; TIGER NAME does not carry it. Do not fix by "
            f"stripping the suffix (breaks Beecher City, Mason City, et al.)"
        )

    if fails:
        print("FAIL")
        for f in fails:
            print(f"  !! {f}")
        return 1
    print("all checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
