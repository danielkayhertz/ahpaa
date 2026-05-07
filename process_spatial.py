"""
process_spatial.py ... Spatial pipeline: AHPAA ... Senate Districts crosswalk.

Outputs:
  output/crosswalk.csv         ... confirmed (municipality ... senate district) pairs
  output/spurious_review.csv   ... flagged micro-overlaps for manual review
  output/unmatched_places.csv  ... AHPAA rows with no TIGER geometry match
  output/dropped_munis.csv     ... munis dropped by keep_geom_type (exact boundary coincidence)
  output/matched_munis.parquet ... matched municipality GeoDataFrame (CRS=5070) for export step
"""

import math
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

AHPAA_PATH = (
    Path(r"C:\Users\bpi\Documents\Claude Code\Missing Middle\data\ihda_raw\AHPAA_2023.xlsx")
)

PLACES_SHP  = DATA_DIR / "il_places_2023" / "tl_2023_17_place.shp"
COUNTY_SHP  = next((DATA_DIR / "il_counties_2023").glob("*.shp"), None)

# Spurious-overlap thresholds (AND logic ... both must be true to flag as micro)
MIN_OVERLAP_M2  = 10_000   # 1 hectare
MIN_OVERLAP_PCT = 0.5      # 0.5% of the smaller polygon

# Polsby-Popper threshold for sliver detection (4pi*area/perimeter^2)
# Values below this are flagged as likely boundary-drawing artifacts
POLSBY_POPPER_THRESHOLD = 0.05   # 0 = infinitely thin, 1 = perfect circle

# Locked crosswalk output columns (renamed from internal names at write time)
CROSSWALK_RENAME = {
    "Place":                    "municipality_name",
    "County":                   "county",
    "_district_id":             "senate_district",
    "Population":               "population",
    "Affordable Housing Share": "affordable_housing_share",
    "Non-Exempt Status":        "non_exempt_status",
    "overlap_area_m2":          "overlap_area_m2",
    "overlap_pct_of_smaller":   "overlap_pct_of_smaller",
    "polsby_popper":            "polsby_popper",
}


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

_ABBREV = {
    r"\bst\.?\b":  "saint",
    r"\bmt\.?\b":  "mount",
    r"\bft\.?\b":  "fort",
    r"\btwp\.?\b": "township",
    r"\bvil\.?\b": "village",
}


def normalize(s: object) -> str:
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = re.sub(r"['\-]", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pat, rep in _ABBREV.items():
        s = re.sub(pat, rep, s)
    return s


# ---------------------------------------------------------------------------
# Step 1 ... Load AHPAA data
# ---------------------------------------------------------------------------

def load_ahpaa() -> pd.DataFrame:
    print("Loading AHPAA ...")
    xl = pd.ExcelFile(AHPAA_PATH, engine="openpyxl")
    assert "Statewide Affordability Listing" in xl.sheet_names, (
        f"Sheet not found. Available: {xl.sheet_names}"
    )
    df = xl.parse("Statewide Affordability Listing", skiprows=5, header=0)

    required = {"Place", "County", "Population", "Affordable Housing Share", "Non-Exempt Status"}
    missing = required - set(df.columns)
    assert not missing, f"Missing columns: {missing}. Got: {list(df.columns)}"

    df = df[df["Place"].notna()].copy()
    df = df[~df["Place"].isin(["Total"])]
    df = df[~df["Place"].astype(str).str.startswith("Note:")]
    assert len(df) > 1200, f"Expected >1200 place rows, got {len(df)}"

    # Normalise share column ... Excel may serialise as "12%" string or 0.12 float
    share = df["Affordable Housing Share"].astype(str).str.replace("%", "", regex=False)
    df["Affordable Housing Share"] = pd.to_numeric(share, errors="coerce")
    if df["Affordable Housing Share"].max() > 1:
        df["Affordable Housing Share"] /= 100
    assert df["Affordable Housing Share"].between(0, 1).all(), (
        "Affordable Housing Share has values outside [0, 1]"
    )

    df["place_norm"]  = df["Place"].apply(normalize)
    df["county_norm"] = df["County"].apply(normalize)

    print(f"  AHPAA rows after cleaning: {len(df)}")
    return df


# ---------------------------------------------------------------------------
# Step 2 ... Load TIGER Counties
# ---------------------------------------------------------------------------

def load_counties() -> gpd.GeoDataFrame:
    print("Loading TIGER Counties ...")
    gdf = gpd.read_file(COUNTY_SHP)
    assert gdf.crs is not None
    # Filter to Illinois if national file was downloaded (STATEFP='17')
    if "STATEFP" in gdf.columns:
        gdf = gdf[gdf["STATEFP"] == "17"].copy()
    elif "STATE_FIPS" in gdf.columns:
        gdf = gdf[gdf["STATE_FIPS"] == "17"].copy()
    gdf = gdf.to_crs(5070)
    gdf["county_name_norm"] = gdf["NAME"].apply(normalize)
    print(f"  {len(gdf)} counties loaded")
    return gdf


# ---------------------------------------------------------------------------
# Step 3 ... Load TIGER Places; derive county via full-geometry sjoin
# ---------------------------------------------------------------------------

def load_places(counties: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    print("Loading TIGER Places ...")
    gdf = gpd.read_file(PLACES_SHP)
    assert gdf.crs is not None and gdf.crs.to_epsg() == 4269, (
        f"Expected EPSG:4269, got {gdf.crs}"
    )

    gdf.geometry = gdf.geometry.apply(make_valid)
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    gdf = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    gdf = gdf.to_crs(5070)
    print(f"  {len(gdf)} polygon parts after explode/filter")

    # Dissolve back to one row per place (GEOID-unique) so multi-part places
    # don't create duplicate matches when joining to AHPAA later
    non_geom = [c for c in gdf.columns if c not in ("geometry", "GEOID")]
    agg_dict = {c: "first" for c in non_geom}
    gdf = gdf.dissolve(by="GEOID", aggfunc=agg_dict).reset_index()
    gdf["muni_area_m2"] = gdf.geometry.area   # full dissolved area
    print(f"  {len(gdf)} places after dissolve to one row per GEOID")

    # Full-geometry intersects sjoin -> one row per (place, county) pair
    # Handles multi-county places (Aurora, Naperville, etc.) correctly
    print("  Joining places to counties (may take a moment) ...")
    place_county = gpd.sjoin(
        gdf[["NAME", "GEOID", "muni_area_m2", "geometry"]],
        counties[["county_name_norm", "geometry"]],
        how="left",
        predicate="intersects",
    ).drop(columns=["index_right"], errors="ignore")
    place_county = place_county[["NAME", "GEOID", "muni_area_m2", "county_name_norm"]].copy()
    # Deduplicate: same place can touch same county at multiple edges after dissolve
    place_county = place_county.drop_duplicates(subset=["GEOID", "county_name_norm"])

    # Merge county assignments back onto the places GDF (one row per place-county)
    places_gdf = gdf.merge(place_county, on=["NAME", "GEOID", "muni_area_m2"], how="left")
    places_gdf = gpd.GeoDataFrame(places_gdf, geometry="geometry", crs=5070)
    places_gdf["name_norm"] = places_gdf["NAME"].apply(normalize)

    print(f"  {len(places_gdf)} (place, county) rows after county join")
    return places_gdf


# ---------------------------------------------------------------------------
# Step 4 ... Join AHPAA ->TIGER Places
# ---------------------------------------------------------------------------

def join_ahpaa_to_places(
    df: pd.DataFrame, places_gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    print("Joining AHPAA ->TIGER Places ...")
    merged = df.merge(
        places_gdf,
        left_on=["place_norm", "county_norm"],
        right_on=["name_norm", "county_name_norm"],
        how="left",
    )

    unmatched = merged[merged["geometry"].isna()][["Place", "County"]].copy()
    unmatched.to_csv(OUTPUT_DIR / "unmatched_places.csv", index=False)
    n_matched = merged["geometry"].notna().sum()
    print(f"  Matched: {n_matched} / {len(df)}  |  Unmatched: {len(unmatched)} ->unmatched_places.csv")

    matched = gpd.GeoDataFrame(
        merged[merged["geometry"].notna()].copy(),
        geometry="geometry",
        crs=5070,
    )
    return matched


# ---------------------------------------------------------------------------
# Step 5 ... Load senate districts (detect column, dissolve after explode)
# ---------------------------------------------------------------------------

_DISTRICT_COL_CANDIDATES = [
    "DISTRICT", "DistrictNo", "DISTRICTNO", "DIST_NO", "DIST_NUM",
    "Senate_Dist", "SENATE_DIST", "Sen_Dist", "SEN_DIST",
    "SLDUST",  # Census TIGER SLDU fallback
    "NAME",    # last resort
]


def _find_senate_shp() -> Path:
    senate_dir = DATA_DIR / "senate_2020"
    shps = list(senate_dir.glob("*.shp"))
    if not shps:
        sys.exit(f"No .shp found in {senate_dir}. Run acquire_boundaries.py first.")
    return shps[0]


def load_senate() -> tuple[gpd.GeoDataFrame, str]:
    shp = _find_senate_shp()
    print(f"Loading senate districts from {shp.name} ...")

    gdf = gpd.read_file(shp)
    assert gdf.crs is not None, "Senate shapefile has no CRS"
    print(f"  Raw senate columns: {list(gdf.columns)}")
    print(f"  Raw row count: {len(gdf)}")

    gdf.geometry = gdf.geometry.apply(make_valid)
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    gdf = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    gdf = gdf.to_crs(5070)

    # Detect district identifier column
    district_col = None
    for col in _DISTRICT_COL_CANDIDATES:
        if col in gdf.columns:
            district_col = col
            break
    if district_col is None:
        sys.exit(
            f"Cannot find a district ID column. Available: {list(gdf.columns)}\n"
            "Update _DISTRICT_COL_CANDIDATES in process_spatial.py."
        )
    print(f"  Using '{district_col}' as district identifier")

    # Dissolve multipart districts before area computation
    gdf = gdf.dissolve(by=district_col).reset_index()
    gdf["district_area_m2"] = gdf.geometry.area
    gdf["_district_id"] = gdf[district_col].astype(str)

    assert len(gdf) == 59, (
        f"Expected 59 senate districts after dissolve, got {len(gdf)}"
    )
    print(f"  {len(gdf)} senate districts after dissolve")
    return gdf, district_col


# ---------------------------------------------------------------------------
# Step 6 ... Intersection + spurious flag
# ---------------------------------------------------------------------------

def compute_crosswalk(
    matched: gpd.GeoDataFrame,
    senate: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("Computing intersection (may take a moment) ...")

    # Rename conflicting columns before overlay
    # TIGER places and senate may both have NAME, geometry, etc.
    senate_overlay = senate[["_district_id", "district_area_m2", "geometry"]].copy()

    intersected = gpd.overlay(
        matched, senate_overlay, how="intersection", keep_geom_type=True
    )
    intersected["overlap_area_m2"] = intersected.geometry.area

    # Detect munis dropped by keep_geom_type (shared exact boundaries ->line/point ->dropped)
    matched_geoids = set(matched["GEOID"])
    intersected_geoids = set(intersected["GEOID"])
    dropped_ids = matched_geoids - intersected_geoids
    if dropped_ids:
        dropped = matched[matched["GEOID"].isin(dropped_ids)][
            ["Place", "County", "GEOID"]
        ].drop_duplicates()
        dropped.to_csv(OUTPUT_DIR / "dropped_munis.csv", index=False)
        print(
            f"  WARNING: {len(dropped_ids)} munis dropped by keep_geom_type "
            "(exact boundary coincidence) ->dropped_munis.csv"
        )
    else:
        print("  No munis dropped by keep_geom_type.")

    intersected["overlap_pct_of_smaller"] = (
        intersected["overlap_area_m2"]
        / intersected[["muni_area_m2", "district_area_m2"]].min(axis=1)
        * 100
    )

    # Polsby-Popper compactness score: 4pi*area / perimeter^2
    # Low values = thin sliver = likely boundary-drawing artifact
    perimeter = intersected.geometry.length
    intersected["polsby_popper"] = (
        (4 * math.pi * intersected["overlap_area_m2"]) / perimeter.pow(2)
    ).clip(upper=1.0)

    # Flag conditions
    is_micro   = (
        (intersected["overlap_area_m2"] < MIN_OVERLAP_M2)
        & (intersected["overlap_pct_of_smaller"] < MIN_OVERLAP_PCT)
    )
    is_sliver  = intersected["polsby_popper"] < POLSBY_POPPER_THRESHOLD
    is_spurious = is_micro | is_sliver

    # Assign human-readable reason to each flagged row
    intersected["flag_reason"] = np.select(
        [is_micro & is_sliver, is_micro, is_sliver],
        ["micro_overlap+sliver", "micro_overlap", "sliver"],
        default="",
    )

    def _to_output(gdf: gpd.GeoDataFrame, include_flag: bool = False) -> pd.DataFrame:
        cols = dict(CROSSWALK_RENAME)
        if include_flag:
            cols["flag_reason"] = "flag_reason"
        available = {c for c in cols if c in gdf.columns}
        sub = gdf[list(available)].copy()
        sub = sub.rename(columns={k: v for k, v in cols.items() if k in available})
        return sub

    confirmed = _to_output(intersected[~is_spurious])

    # A spurious overlap only needs review when it is the *sole* evidence of a
    # municipality-district relationship.  If the same (Place, County, district)
    # pair already has a confirmed (non-spurious) overlap, the spurious row is
    # redundant and can be discarded.
    confirmed_keys = set(
        zip(
            intersected.loc[~is_spurious, "Place"],
            intersected.loc[~is_spurious, "County"],
            intersected.loc[~is_spurious, "_district_id"],
        )
    )
    spurious_df = intersected[is_spurious].copy()
    already_confirmed = spurious_df.apply(
        lambda r: (r["Place"], r["County"], r["_district_id"]) in confirmed_keys,
        axis=1,
    )
    spurious_orphans = _to_output(spurious_df[~already_confirmed], include_flag=True)
    n_redundant = already_confirmed.sum()

    n_micro  = is_micro.sum()
    n_sliver = is_sliver.sum()
    n_both   = (is_micro & is_sliver).sum()
    print(f"  Confirmed overlaps: {len(confirmed)}")
    print(f"  Flagged total: {is_spurious.sum()}  "
          f"(micro-overlap: {n_micro}, sliver: {n_sliver}, both: {n_both})")
    print(f"  Redundant flags (pair already confirmed): {n_redundant} discarded")
    print(f"  Orphan flags needing review: {len(spurious_orphans)}")
    return confirmed, spurious_orphans


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df      = load_ahpaa()
    counties = load_counties()
    places  = load_places(counties)
    matched = join_ahpaa_to_places(df, places)
    senate, district_col = load_senate()
    confirmed, spurious  = compute_crosswalk(matched, senate)

    confirmed.to_csv(OUTPUT_DIR / "crosswalk.csv", index=False)
    spurious.to_csv(OUTPUT_DIR  / "spurious_review.csv", index=False)
    print("Wrote crosswalk.csv and spurious_review.csv")

    # Persist matched geometry for export step
    matched.to_parquet(OUTPUT_DIR / "matched_munis.parquet")
    # Also persist senate for export step
    senate[["_district_id", "district_area_m2", "geometry"]].to_parquet(
        OUTPUT_DIR / "senate_dissolved.parquet"
    )
    print("Wrote matched_munis.parquet and senate_dissolved.parquet")
    print("\nDone.")


if __name__ == "__main__":
    main()
