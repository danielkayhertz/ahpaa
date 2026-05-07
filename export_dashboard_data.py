"""
export_dashboard_data.py — Build output/dashboard_data.js for dashboard.html.

Reads:
  output/matched_munis.parquet  — matched municipality GeoDataFrame (EPSG:5070)
  output/crosswalk.csv          — confirmed (municipality × senate district) pairs
  output/senate_dissolved.parquet — dissolved senate district GeoDataFrame (EPSG:5070)

Writes:
  output/dashboard_data.js
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

MUNIS_PARQUET   = OUTPUT_DIR / "matched_munis.parquet"
SENATE_PARQUET  = OUTPUT_DIR / "senate_dissolved.parquet"
CROSSWALK_CSV   = OUTPUT_DIR / "crosswalk.csv"
DASHBOARD_JS    = OUTPUT_DIR / "dashboard_data.js"


# ---------------------------------------------------------------------------
# Bucket assignment
# ---------------------------------------------------------------------------

def assign_bucket(row: pd.Series) -> str:
    """
    Non-Exempt  — authoritative per IHDA's non_exempt_status column
    affordable-low  — Exempt AND share ≤ 0.25  (10–25%)
    affordable-high — Exempt AND share > 0.25  (>25%)
    """
    if str(row.get("non_exempt_status", "")).strip() == "Non-Exempt":
        return "non-exempt"
    share = row.get("affordable_housing_share", 0) or 0
    return "affordable-low" if share <= 0.25 else "affordable-high"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    for p in (MUNIS_PARQUET, SENATE_PARQUET, CROSSWALK_CSV):
        if not p.exists():
            sys.exit(f"Missing required file: {p}\nRun process_spatial.py first.")

    # ---- Load crosswalk ---------------------------------------------------
    crosswalk = pd.read_csv(CROSSWALK_CSV)
    print(f"Crosswalk rows: {len(crosswalk)}")

    # ---- Load municipality geometries ------------------------------------
    munis = gpd.read_parquet(MUNIS_PARQUET)
    assert munis.crs is not None and munis.crs.to_epsg() == 5070, (
        f"Expected EPSG:5070, got {munis.crs}"
    )

    # Deduplicate: keep one row per (Place, County) — each is a unique AHPAA entry
    key_cols = ["Place", "County", "Affordable Housing Share",
                "Non-Exempt Status", "Population"]
    munis_unique = munis[key_cols + ["geometry"]].drop_duplicates(
        subset=["Place", "County"]
    ).copy()

    # Aggregate senate districts per (Place, County) from the crosswalk
    districts_per_muni = (
        crosswalk.groupby(["municipality_name", "county"])["senate_district"]
        .apply(lambda x: sorted(set(x.astype(str))))
        .reset_index()
        .rename(columns={"senate_district": "senate_districts"})
    )

    munis_unique = munis_unique.merge(
        districts_per_muni,
        left_on=["Place", "County"],
        right_on=["municipality_name", "county"],
        how="left",
    )
    munis_unique["senate_districts"] = munis_unique["senate_districts"].apply(
        lambda v: v if isinstance(v, list) else []
    )

    # Assign affordability bucket
    munis_unique["bucket"] = munis_unique.apply(
        lambda r: assign_bucket({
            "non_exempt_status":        r.get("Non-Exempt Status"),
            "affordable_housing_share": r.get("Affordable Housing Share"),
        }),
        axis=1,
    )

    # ---- Simplify and reproject to WGS84 ---------------------------------
    print("Simplifying municipality geometries (20m tolerance in EPSG:5070) …")
    munis_unique.geometry = munis_unique.geometry.simplify(tolerance=20, preserve_topology=True)
    munis_wgs84 = munis_unique.to_crs(4326)

    # ---- Build municipality GeoJSON features -----------------------------
    muni_features = []
    for _, row in munis_wgs84.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        share = row.get("Affordable Housing Share") or 0
        muni_features.append({
            "type": "Feature",
            "geometry": row.geometry.__geo_interface__,
            "properties": {
                "municipality_name": row.get("Place", ""),
                "county":            row.get("County", ""),
                "population":        int(row["Population"]) if pd.notna(row.get("Population")) else None,
                "affordable_housing_share": round(float(share), 4),
                "non_exempt_status": row.get("Non-Exempt Status", ""),
                "bucket":            row["bucket"],
                "senate_districts":  row["senate_districts"],
            },
        })
    print(f"  Municipality features: {len(muni_features)}")

    # ---- Load and simplify senate district geometries --------------------
    senate = gpd.read_parquet(SENATE_PARQUET)
    print("Simplifying senate geometries (100m tolerance in EPSG:5070) …")
    senate.geometry = senate.geometry.simplify(tolerance=100, preserve_topology=True)
    senate_wgs84 = senate.to_crs(4326)

    district_features = []
    for _, row in senate_wgs84.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        district_features.append({
            "type": "Feature",
            "geometry": row.geometry.__geo_interface__,
            "properties": {"senate_district": str(row["_district_id"])},
        })
    print(f"  Senate district features: {len(district_features)}")

    # ---- Build crosswalk records -----------------------------------------
    crosswalk_records = crosswalk.to_dict(orient="records")
    # Ensure numeric columns are JSON-serialisable
    for rec in crosswalk_records:
        for k, v in rec.items():
            if hasattr(v, "item"):  # numpy scalar
                rec[k] = v.item()

    # ---- Write dashboard_data.js -----------------------------------------
    spurious_count = 0
    spurious_path = OUTPUT_DIR / "spurious_review.csv"
    if spurious_path.exists():
        spurious_count = len(pd.read_csv(spurious_path))

    payload = {
        "municipalities": {"type": "FeatureCollection", "features": muni_features},
        "districts":      {"type": "FeatureCollection", "features": district_features},
        "crosswalk":      crosswalk_records,
        "meta": {
            "spurious_count": spurious_count,
            "total_munis":    len(muni_features),
            "total_districts": len(district_features),
        },
    }

    js_content = "const DASHBOARD_DATA = " + json.dumps(payload, allow_nan=False) + ";\n"
    DASHBOARD_JS.write_text(js_content, encoding="utf-8")

    size_mb = DASHBOARD_JS.stat().st_size / 1_048_576
    print(f"\nWrote {DASHBOARD_JS}  ({size_mb:.1f} MB)")
    print("Done. Open dashboard.html in a browser.")


if __name__ == "__main__":
    main()
