DOES NOT SURVIVE

The map leaves out the main senate district for 45 municipalities (1,306,736
residents), including Joliet. It also shows 34 of them in no district at all.
The cause is the same shape filter flagged on 2026-08-02. That fix was never
applied, and the pipeline outputs are unchanged since 2026-05-07.

```
Tier: Deep (scored). Ran Standard lanes A and C plus a full independent recompute in the main session.
Raised by: a spatial join with no cardinality assertion; name-based IHDA-to-TIGER matching;
           2023 places against a 2021 plan; a public dashboard
Lanes: A (data/pipeline), C (dashboard as claim). B and D were not re-run, because the
       2026-08-02 review already ran two blind replications on these same files.
```

## Claim under review

`dashboard.html:178-179`: "AHPAA Affordability × Illinois Senate Districts / 2023 IHDA
Affordable Housing Planning and Accountability Act — municipality crosswalk."

The interface is the claim:
- each popup's district list (`dashboard.html:447`);
- the district rosters and counts (`:751`, `:782-784`);
- the legend and badges (`:189-199`, `:591`).

## Why Joliet is not in district 49 (the reported defect)

`process_spatial.py:325-329` drops any overlap whose Polsby-Popper compactness is below
0.05, whatever its size:

```python
is_micro    = (overlap_area_m2 < 10_000) & (overlap_pct_of_smaller < 0.5)
is_sliver   = polsby_popper < 0.05
is_spurious = is_micro | is_sliver        # <- OR: shape alone discards a row
```

Joliet's boundary is very irregular because of its annexation fingers, so its two largest
overlaps score as "slivers":
- 58% of the city lies in district 43;
- 32% lies in district 49.

Its three smallest overlaps (9% of the city combined) are compact enough to survive. The
map therefore shows Joliet in 19, 38 and 40 only. **District 43, Joliet's main district,
is missing as well as 49.**

```
$ python -I -c "...overlay of raw TIGER 2023 Joliet x raw 'Senate Plan.shp'..."
     NAME  DISTRICT         km2        pct        pp
3  Joliet        43  101.143299  58.404700  0.011539
4  Joliet        49   55.700153  32.163780  0.034664
1  Joliet        38    8.250253   4.764068  0.089448
0  Joliet        19    6.071862   3.506167  0.081841
2  Joliet        40    2.011074   1.161285  0.262015
$ grep -i joliet output/spurious_review.csv
sliver,Joliet,0.011539192,150323,Exempt,0.686319395,Will,43,58.40470042,101143298.9,
sliver,Joliet,0.034663532,150323,Exempt,0.686319395,Will,49,32.16377957,55700153.38,
```

## Findings

### F1 · The shape filter drops 81 real overlaps, and 45 municipalities lose their main district

**Severity** Fatal
**Status** CONFIRMED
**Lane** main-session recompute; corroborated by A and C
**Location** `process_spatial.py:325-329` → `crosswalk.csv` → `dashboard_data.js` → `dashboard.html:447`, `:303-346`

**What is wrong.**
- The OR above discards 81 overlaps that pass the size test (≥1 ha or ≥0.5%).
- For 45 municipalities, the district holding most of their land is among the discards.
- 34 municipalities (pop. 518,385) end up in no district at all. They appear on the map
  with a popup reading "none in crosswalk" and are left out of every roster.
- The map also draws district outlines from geometry. Clicking SD 43 therefore zooms to a
  district that visibly contains Joliet, while Joliet is absent from the SD 43 roster.

This merges prior F1, F2 and F8 with lane C's L1, because one fix corrects all of them.

**Demonstration.** This is an independent overlay of the raw shapefiles. It does not use
the pipeline's parquet files, and it matches places by name within county using its own
normaliser. It agrees with the pipeline on every pair the pipeline kept: there are 0 false
positives.

```
$ python -I scratchpad/recompute.py scratchpad/pairs.csv
AHPAA rows w/ place+county: 1299  dup place+county: 0
rows after join: 1299  (fan-out 0 )  unmatched: 11
matched to CDP: 0 []
all nonzero pairs: 1787  >=1ha or >=0.5%: 1671
$ python -I -c "...diff pairs.csv vs crosswalk.csv..."
crosswalk pairs not in raw recompute: 0
raw pairs missing from crosswalk: 197
  of which micro (<1 ha): 116  larger: 81  >=5% of muni: 57  >=50%: 44
municipalities whose PRIMARY district (largest land share) is missing from map: 45  pop 1306736
       Place  DISTRICT   pct_muni  Population
      Aurora        42  51.167745    183447.0
      Joliet        43  58.404700    150323.0
    Rockford        34  85.354511    148942.0
 Springfield        48  96.358336    114672.0
       Elgin        33  51.358710    114156.0
 Bloomington        44  50.848165     78372.0
  Belleville        57 100.000000     42463.0
Crystal Lake        32  48.099541     40082.0
```

**Headline impact.**

| Figure | Shown | Corrected |
|---|---|---|
| Municipality–district pairs | 1,590 | 1,671 |
| Municipalities with any district | 1,254 | 1,288 |
| Municipalities with no district | 34 | 0 |
| Non-Exempt pairs | 74 across 21 districts | 76 across 22 |
| SD 9 Non-Exempt roster | 5 | 6 (adds Northfield) |
| SD 10 Non-Exempt roster | 0 | 1 (adds Park Ridge) |

Corrected district lists for the largest affected cities:

| City | Shown | Corrected |
|---|---|---|
| Joliet | 19, 38, 40 | 19, 38, 40, 43, 49 |
| Aurora | 49 | 21, 25, 42, 49 |
| Rockford | 35 | 34, 35, 45 |
| Springfield | none | 48, 54 |
| Elgin | 22, 25, 35 | 22, 25, 33, 35 |
| Bloomington | 46, 53 | 44, 46, 53 |

**Fix requires.**
1. Set `is_spurious = is_micro`, or gate the sliver test on size.
2. Re-run `process_spatial.py` and `export_dashboard_data.py`.

### F2 · "By District" counts municipality–district pairs and labels them "municipalities"

**Severity** Material
**Status** CONFIRMED
**Lane** A, C
**Location** `dashboard.html:751` (`totalMunis += filtered.length;`), `:782-784`

**What is wrong.** A municipality that spans k districts is counted k times. Chicago alone is
counted 21 times.

**Demonstration.**
```
$ node scratchpad/laneC/a5.js
default | muni view: "1,254 municipalities" | district view: "1,590 municipalities across 59 districts" (distinct munis=1254)
Non-Exempt only | muni view: "44 municipalities" | district view: "74 municipalities across 21 districts" (distinct munis=44)
```

**Headline impact.**
- With all filters on, "1,590 municipalities" should read 1,254 (1,288 after F1 is fixed).
- With the Non-Exempt filter, "74 municipalities" should read 44.

**Fix requires.** Count distinct (name, county) pairs, or relabel the count
"municipality–district pairs".

### F3 · Four municipalities exempt for having under 1,000 people are labelled "Affordable 10–25%"

**Severity** Material
**Status** CONFIRMED
**Lane** A, C. Lane A's bucket count of 58 was wrong and is corrected here to 54.
**Location** `export_dashboard_data.py:41-42` (`assign_bucket`); `dashboard.html:195`, `:591`

**What is wrong.**
- `assign_bucket` puts every Exempt place with share ≤ 0.25 into "affordable-low".
- IHDA marks four places Exempt because their population is under 1,000, even though their
  shares are below 10%. They end up in "affordable-low".
- For example, Mettawa has a share of 0.0% and shows an "Affordable (10–25%)" badge.

**Demonstration.**
```
$ python -I -c "...xlsx: Exempt & share<0.10..."
       Place  County  Population  Affordable Housing Share
        Golf    Cook       524.0                  0.006130
Indian Creek    Lake       834.0                  0.034024
     Mettawa    Lake       647.0                  0.000000
Trout Valley McHenry       542.0                  0.029528
$ python -I -c "...Counter of bucket in dashboard_data.js..."
Counter({'affordable-high': 1190, 'affordable-low': 54, 'non-exempt': 44})
```

**Headline impact.** The 10–25% bucket drops from 54 to 50. Four places need a separate
"Exempt (population under 1,000)" bucket.

**Fix requires.** In `assign_bucket`, check population before share.

### F4 · Hygiene: wrong as shown, but no quoted number moves

| # | Finding | Location | Lane |
|---|---|---|---|
| a | The header names the "Planning and **Accountability** Act". The xlsx and the IHDA PDF both say "Affordable Housing Planning and **Appeal** Act" | `dashboard.html:179` | A, C |
| b | The footer calls all 197 excluded overlaps "micro-overlap(s) flagged for manual review". 81 of them are not micro (Springfield SD 48 is 96% of the city), and 162 of the 197 were never reviewed | `dashboard.html:990` | C |
| c | District lists are sorted as text in 24 popups (e.g. Chicago "1, 10, 11, …, 2, 20") | `export_dashboard_data.py:74` | A, C |
| d | Search does substring matching on district numbers ("4" returns 15 districts) and does not re-style the map | `dashboard.html:576-580`, `:928-931` | C |
| e | The CSV export writes the raw fraction and IHDA's status, while the screen shows a % and a bucket badge | `dashboard.html:948-955` | C |
| f | The footer says "ILSBE 2020 Senate Districts", but the geometry is the 2021 enacted plan (in use since 2022). The ACS 2017–21 vintage behind the shares is not stated | `dashboard.html:267` | A, C |
| g | Sandoval's asterisk is displayed, but its footnote (property taxes not factored into the share) is dropped | `process_spatial.py:107` | A |
| h | Membership depends on an arbitrary 1 ha floor. Raising it to 10 ha drops 20 pairs. 17 municipalities are multi-district only because of overlaps under 1% of their area. 4 pairs exist only on land annexed after 2020 | `process_spatial.py:36-37` | A |

### F5 · Hygiene: the 2026-08-02 review's counts and check script are slightly off

**Status** CONFIRMED
**Lane** A, verified in main session

The prior review counted every non-zero intersection as a "true pair":
- It reported 1,793 true pairs. The figure under the size rule is 1,671.
- It reported 197 discarded overlaps. Only 81 of them are real losses; the other 116 fail
  the micro rule and would be dropped anyway.

Its `review_checks.py` expects 1,793 ± 5 pairs and 5 districts for Aurora. Aurora's fifth
"overlap" is 0.015 m², so a correctly fixed pipeline gives 4 districts and could never pass
that check. This changes nothing on the map.

```
Aurora all nonzero: [[21.0, 15571.028, 0.013], [25.0, 55750861.201, 46.8], [35.0, 0.015, 0.0], [42.0, 60954024.16, 51.168], [49.0, 2405418.041, 2.019]]
```

`output/review_checks_2026-11-18.py` supersedes it.

### Carried forward from 2026-08-02, still open

- **F6:** Wilmington City/Village, Windsor City/Village and Alvin are unmatched, because IHDA
  appends City or Village to tell same-named places apart.

### PLAUSIBLE

- **P1 · Land overlap versus residents (Material if it holds).** 38 kept pairs cover under
  1% of their municipality's area and may have no residents. Resolve this by summing 2020
  block POP20 over place ∩ district.
- **P2 · Chicago's statutory treatment.** The statute may exclude municipalities over
  1,000,000 (310 ILCS 67/15). IHDA lists Chicago as "Exempt" at 47.2%, and the dashboard
  shows it as "Affordable >25%". This was not verified: ilga.gov refused the fetch.

## Dismissed

- **Wrong senate plan vintage.** All 59 ILSBE districts are at least 99.99% inside the
  matching Census TIGER 2023 SLDU district. Re-running against TIGER gives 1,669 pairs
  against 1,671.
- **Join fan-out or wrong-place matches.** 1,299 rows went in and 1,299 came out. There are
  0 matches to CDPs and 0 duplicate GEOIDs. The five places with less than half their area
  in the listed county are genuinely multi-county.
- **False positives in the crosswalk.** 0 crosswalk pairs are absent from the raw recompute.
- **xlsx mis-parsing.** The xlsx has 1,298 rows, matching IHDA's own total. Population and
  share have 0 mismatches against the IHDA PDF. 44 places are Non-Exempt, matching IHDA's
  NELG total.
- **The "Non-Exempt (<10%)" and "Affordable >25%" legend ranges.** Both hold for every row.
- **Null shares or populations, CSV comma mangling, and gaps in the population filter.**
  There are none.

## Layer gate

Re-derived on corrected data:

| Data-layer finding | Downstream number | Shown | Corrected |
|---|---|---|---|
| F1 | Total pairs | 1,590 | 1,671 |
| F1 | Municipalities with a district | 1,254 | 1,288 |
| F1 | Popups reading "none in crosswalk" | 34 | 0 |
| F1 | Non-Exempt pairs | 74 across 21 districts | 76 across 22 |
| F1 → F2 | "By District" headline | "1,590 municipalities" | 1,288 municipalities (1,671 pairs) |
| F1 | F3 bucket counts | — | Unaffected: the bucket is per municipality, and none of the 4 is among the 34 |

## Check script

`output/review_checks_2026-11-18.py` exits 1 with 18 failures today. It encodes:
- the corrected district sets for 8 cities, Joliet's {19, 38, 40, 43, 49} among them;
- the rule that every municipality's primary district is present;
- the pair and municipality totals;
- the F2, F3 and hygiene checks.

---

## Fixes applied 2026-11-18 (after the review)

`python output/review_checks_2026-11-18.py` → `all checks pass`, exit 0.

| Finding | Change | Result |
|---|---|---|
| F1 | `process_spatial.py`: `is_spurious = is_micro`. Polsby-Popper is kept as an informational column only. Added a `pct_of_municipality` column. | 1,677 pairs and 1,293 municipalities. Every municipality has its primary district. Joliet = 19, 38, 40, 43, 49 |
| F6 | `process_spatial.py`: strips City/Village only when the same base name appears with both suffixes, and indexes TIGER's parenthetical names ("Alvan (Alvin)"). Added a cardinality assertion on the join. | Wilmington ×2, Windsor ×2 and Alvin matched. Beecher City and Mason City are unchanged. 5 remain unmatched (see below) |
| F2 | `dashboard.html`: the "By District" count is now distinct municipalities, with the row count shown separately | "1,293 municipalities across 59 districts (1,677 municipality–district rows)" |
| F3 | New `exempt-small` bucket, labelled "Exempt (pop. <1,000)", with its own legend button and colour | Golf, Indian Creek, Mettawa and Trout Valley are no longer labelled 10–25% |
| F4a, b, c, f | Act renamed to "Planning and Appeal Act". Footer now describes the 116 micro exclusions accurately. Districts are sorted numerically. Plan label and ACS vintage added | — |
| F4d | A numeric search now matches a district exactly ("49" returns the 9 municipalities in SD 49) | Search still does not re-style the map |

**Still open:**
- F4e: CSV export labels.
- F4g: Sandoval footnote.
- F4h: the 1 ha floor is a judgement call.
- P1: residents versus land.
- P2: Chicago's statutory status.
- 5 unmatched places. Alorton, Cahokia and Centreville merged into Cahokia Heights in 2021, and IHDA still lists the old names. Clear Lake and Time have no 2023 TIGER place.
- `output/review_checks.py` (2026-08-02) is marked superseded. It still fails by design, because its expected counts include micro overlaps.
