DOES NOT SURVIVE

The crosswalk omits the senate districts covering most of Illinois's largest
municipalities, and omits 34 municipalities entirely — Springfield among them.
One operator in `process_spatial.py` is responsible.

```
Tier: Deep
Raised by: municipality x district spatial join with no cardinality assertion;
           name-based IHDA-to-TIGER matching; a single 2023 vintage; a public
           artifact (github.com/danielkayhertz/ahpaa)
Lanes: A (data/pipeline), B (inference), C (claims vs. evidence),
       D (replication, run twice — R and Python)
```

**Run status.** All four lanes completed. F1-F6 below come from independent
recomputation in the main session and from both Lane D replications; F7 onward
come from lanes A, B and C, which ran last and are reported in the second half
of this document. **No formal adjudication step was run** — severities are the
reviewer's, and lane findings were spot-checked rather than each re-run. One
lane finding was checked and found overstated; that is noted where it appears.
F1-F3 are demonstrated and reproducible as written.

## Claim under review

This project has no prose report; the deliverable is the data. Its implicit
claim is that `output/crosswalk.csv` maps every Illinois municipality to the
senate district(s) it lies in, and that `output/spurious_review.csv` holds only
genuinely spurious overlaps.

## F1 · A compactness test discards real overlaps

**Severity** Fatal · **Status** CONFIRMED · **Location** `process_spatial.py:325-329`

**What is wrong.**

```python
is_micro  = (overlap_area_m2 < MIN_OVERLAP_M2) & (overlap_pct_of_smaller < MIN_OVERLAP_PCT)
is_sliver = intersected["polsby_popper"] < POLSBY_POPPER_THRESHOLD
is_spurious = is_micro | is_sliver
```

The comment at line 38 reads "AND logic ... both must be true to flag as micro."
That is true of `is_micro`. But `is_spurious` is an **OR**, so `is_sliver` alone
discards a row with no size condition of any kind.

Polsby-Popper measures compactness. A municipality-district intersection is
routinely elongated, because district boundaries follow rivers, rail lines and
highways. Compactness carries no information about whether an overlap is real.

**Demonstration.**

```
$ python -c "
import csv
sp=list(csv.DictReader(open('output/spurious_review.csv',encoding='utf-8')))
big=[r for r in sp if float(r['overlap_area_m2'])>1_000_000]
from collections import Counter
print('discarded overlaps >1 km2: %d of %d'%(len(big),len(sp)))
print('combined area: %.1f km2'%(sum(float(r['overlap_area_m2']) for r in big)/1e6))
print('flag reasons among them:',Counter(r['flag_reason'] for r in big))"
discarded overlaps >1 km2: 58 of 197
combined area: 1781.7 km2
flag reasons among them: Counter({'sliver': 58})
```

All 58 large discards were flagged `sliver`; none by size. The most extreme is
Hampshire, whose district-35 overlap is **100.0%** of the municipality — the
village lies wholly inside one district — discarded because the resulting shape
is not compact.

**Headline impact.** 203 of 1,793 true (municipality, district) pairs are absent
from the deliverable.

**Fix requires.** `is_spurious = is_micro`, or gate the sliver test on size —
`is_sliver & (overlap_pct_of_smaller < 1.0)`. Then re-run and re-review.

## F2 · 34 municipalities are absent from the crosswalk entirely

**Severity** Fatal · **Status** CONFIRMED

**What is wrong.** For 34 municipalities every district overlap tripped the
sliver test, so they appear nowhere in `crosswalk.csv` and nowhere in the
dashboard. Nothing discloses their absence. Combined population **518,385**.

**Demonstration.**

```
$ python -c "
import csv
cw={r['municipality_name'] for r in csv.DictReader(open('output/crosswalk.csv',encoding='utf-8'))}
sp=[r for r in csv.DictReader(open('output/spurious_review.csv',encoding='utf-8'))]
gone={r['municipality_name'] for r in sp}-cw
pops={r['municipality_name']:float(r['population'] or 0) for r in sp if r['municipality_name'] in gone}
print('in spurious_review but never in crosswalk:',len(gone))
for n,p in sorted(pops.items(),key=lambda x:-x[1])[:5]: print('   %-16s pop=%8.0f'%(n,p))
print('total population: %.0f'%sum(pops.values()))"
in spurious_review but never in crosswalk: 34
   Springfield      pop=  114672
   Belleville       pop=   42463
   Danville         pop=   29534
   Granite City     pop=   27336
   Lockport         pop=   26070
total population: 518385

$ python -c "
import csv
print('Springfield rows in crosswalk:',sum(1 for r in csv.DictReader(open('output/crosswalk.csv',encoding='utf-8')) if r['municipality_name']=='Springfield'))
for r in csv.DictReader(open('output/spurious_review.csv',encoding='utf-8')):
    if r['municipality_name']=='Springfield':
        print('   d=%-3s %-8s area_m2=%12.0f pct=%7.3f Legit?=%r'%(r['senate_district'],r['flag_reason'],float(r['overlap_area_m2']),float(r['overlap_pct_of_smaller']),r.get('Legit?','')))"
Springfield rows in crosswalk: 0
   d=48  sliver   area_m2=   168689920  pct= 96.358  Legit?=''
   d=54  sliver   area_m2=     6375287  pct=  3.642  Legit?=''
```

Springfield's district-48 overlap is **96.4% of the city** and was discarded as
a sliver. The state capital is missing from a municipality-to-senate-district
crosswalk built for legislative advocacy.

**Headline impact.** Any district roster, count, or share drawn from this
crosswalk is wrong for 34 municipalities and roughly half a million residents.

## F3 · Two blind replications agree with each other, not with the pipeline

**Severity** Fatal · **Status** CONFIRMED

Two implementations were written from a prose specification with the original
code and all intermediate outputs withheld: one in R (`sf` 1.1.2, GEOS 3.14.1),
one in Python (geopandas). Tolerance was declared before either ran — counts
must match exactly.

| | R | Python | `crosswalk.csv` |
|---|---|---|---|
| total pairs | **1,793** | **1,793** | 1,590 |
| Springfield | 2 | 2 | **0** |
| Aurora | 5 | 5 | **1** |
| Rockford | 3 | 3 | **1** |
| Joliet | 5 | 5 | **3** |
| Bloomington | 3 | 3 | **2** |
| Naperville | 7 | 7 | 7 |
| Chicago | 21 | 21 | 21 |

The replications match exactly. The pipeline diverges by 203 pairs (12.8%), far
outside tolerance. **The pipeline is the implementation that is wrong**; F1 is
the mechanism. Naperville and Chicago agree across all three because none of
their overlaps tripped the sliver test — they are the controls showing the
pipeline is correct when the bug does not fire.

Concretely: Rockford appears only under district 35, covering 6.2% of the city,
while district 34 covering 85.4% was discarded. Aurora appears only under
district 49 at 2.0%, having lost districts 42 (51.2%) and 25 (46.8%).

## F4 · The manual review that would have caught this was never completed

**Severity** Material · **Status** CONFIRMED

`spurious_review.csv` carries a `Legit?` column for human adjudication. It is
blank for **162 of 197 rows**, including every large discard in F1 and both
Springfield rows. The safety net was built, left unused, and the unreviewed
output published.

## F5 · `overlap_pct_of_smaller` cannot be summed or compared across rows

**Severity** Material · **Status** CONFIRMED

The denominator switches between the municipality and the district depending on
which is smaller, so the column means different things in different rows.

```
Naperville   7 districts   overlap_pct sums to  100.000
Chicago     21 districts   overlap_pct sums to 1101.005
```

The column name is honest about this; a dashboard field a reader takes as
"share of this municipality" is not.

**Fix requires.** Emit `pct_of_municipality` as a separate unambiguous column.

## F6 · Five municipalities fail to match on a disambiguating suffix

**Severity** Material · **Status** CONFIRMED

`unmatched_places.csv` lists 10; both replications matched all but 5. The extra
five are `Wilmington City`, `Wilmington Village`, `Windsor City`,
`Windsor Village` and `Alvin`. IHDA appends City/Village to disambiguate
same-named municipalities in different counties; TIGER's `NAME` does not carry
it, so the `(place_norm, county_norm)` join fails.

The fix is **not** to strip a trailing "City" — that breaks seven genuine names
(Beecher City, Mason City, Norris City, Pearl City, Standard City, Junction
City, Wayne City). Match on GEOID, or special-case the disambiguating suffix
only where IHDA has two rows sharing a base name.

Alorton, Cahokia and Centreville are correct non-matches: they merged into
Cahokia Heights in 2021 and have no 2023 TIGER place.

## Dismissed

- **Senate districts double-counting.** Checked: the 59 dissolved districts have
  zero mutual overlap. Not a source of inflated pairs.
- **Wrong projection for area.** Checked: EPSG:5070 throughout, correct for
  equal-area work. Both replications reproduce the pipeline's areas where rows
  exist.
- **Chicago's percentages not summing to 100%** (98.87%). Real but benign:
  6.89 km² of Chicago's Lake Michigan area lies outside the senate plan's
  lakefront boundary. Every other municipality covers to ~100.000%.

## Check script

`output/review_checks.py`, written alongside this report. It fails while F1 and
F2 are open, and will keep failing if either regresses.

---

# Additional findings from lanes A, B and C

The three lanes completed after this report's first section was written. Each
worked independently, was not told what the others or the reviewer had found,
and reached **DOES NOT SURVIVE** on its own. Their findings below are **not
adjudicated** — the reviewer spot-checked the ones marked *verified* and did not
re-run the rest.

## F7 · District-level aggregates double-count by roughly 6x

**Severity** Fatal · **Status** CONFIRMED · **Lane** B · *verified*

Municipality-level attributes — `population`, `affordable_housing_share` — are
carried whole onto every (municipality, district) row. Chicago's 2,742,119
appears on all 21 of its rows. Any sum or mean over the crosswalk therefore
counts a municipality once per district it touches.

```
$ python -c "...sum population column vs. distinct municipalities..."
sum of population column over all crosswalk rows : 73,384,283
true sum over distinct municipalities            : 10,664,345
inflation                                        : 588.1%
```

Illinois has roughly 12.5 million residents. Anything aggregated from this file
at district level is wrong unless it first deduplicates to distinct
municipalities, or apportions by the overlap share.

**Fix requires.** Decide the unit. If a district roster is wanted, deduplicate.
If district population is wanted, apportion by overlap area — and note that
land-area apportionment is a poor proxy for population, which is the reason to
prefer block-level allocation if the number matters.

## F8 · The dashboard never discloses what it omits

**Severity** Fatal · **Status** CONFIRMED · **Lane** C · *verified*

34 municipalities render on the map but appear in no district and no table row,
and nothing in the interface says so. A user filtering to a senate district
sees a roster that is silently incomplete. Springfield is the clearest case.

Lane C also found the footer describes the 197 excluded pairs as
"micro-overlap(s) flagged for manual review" — of which 44 are full-containment
overlaps, and 162 were never reviewed. The label asserts both a magnitude and a
process that the data does not support.

## F9 · Other lane findings, not individually verified

| # | Finding | Sev | Lane |
|---|---|---|---|
| — | 31 whole-municipality containments deleted by the filter | Fatal | A |
| — | 4 of the 10 "unmatched" municipalities have exact Census place matches | Material | A |
| — | 19 Chicago rows use the district, not the municipality, as the pct base | Material | A |
| — | "By District" presents 1,590 pairs as a count of municipalities | Material | C |
| — | Legend and status badge assert share ranges the bucket field does not encode | Material | C |
| — | District mean of `affordable_housing_share` is a mean of ratios, diverging up to 31 points from the population-weighted figure | Material | B |
| — | 7 district rosters consist of a single municipality; percentages computed on those denominators | Material | B |
| — | Export CSV labelling differs from the on-screen table for the same field | Hygiene | C |
| — | Every discretionary threshold is set in the direction that shrinks rosters | Hygiene, **PLAUSIBLE** | B |

The reviewer checked one of these and found it overstated: Lane C's export
finding claimed the CSV uses "a header the UI renders as a percent." The export
has its own header, `Affordable Housing Share`, consistent with the fraction it
emits. The inconsistency is between two views' labels, which is milder than
stated. Treat the unverified rows above as leads, not conclusions.

## Convergence

Five independent assessments — the reviewer's recomputation, two blind
replications, and three lanes — reached the same verdict without coordination.
The disagreements between them are about which finding is most important, not
about whether the crosswalk is sound.
