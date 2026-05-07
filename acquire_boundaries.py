"""
acquire_boundaries.py — Download and cache all boundary shapefiles.

Downloads:
  - Census TIGER/Line 2023 IL Places  → data/il_places_2023/
  - Census TIGER/Line 2023 IL Counties → data/il_counties_2023/
  - ILSBE 2020 Senate Districts        → data/senate_2020/
    (falls back to Census TIGER SLDU 2023 if ILSBE is unreachable or returns bad data)

Safe to re-run: skips downloads if the target .shp already exists.
"""

import io
import sys
import zipfile
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

TIGER_PLACES_URL  = "https://www2.census.gov/geo/tiger/TIGER2023/PLACE/tl_2023_17_place.zip"
TIGER_COUNTY_URL  = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_5m.zip"
TIGER_SLDU_URL    = "https://www2.census.gov/geo/tiger/TIGER2023/SLDU/tl_2023_17_sldu.zip"

ILSBE_BASE        = "https://www.elections.il.gov/shape/2020_Senate_Districts/"
ILSBE_FILES       = [
    "Senate%20Plan.shp",
    "Senate%20Plan.dbf",
    "Senate%20Plan.prj",
    "Senate%20Plan.shx",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

SHP_MAGIC = b"\x00\x00\x27\x0a"  # first 4 bytes of a valid .shp file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download_zip(url: str, dest_dir: Path, label: str) -> None:
    print(f"  Downloading {label} …")
    r = requests.get(url, headers=BROWSER_HEADERS, timeout=180)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(dest_dir)
    print(f"  Extracted {len(list(dest_dir.iterdir()))} files to {dest_dir}")


def _valid_shp(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == SHP_MAGIC
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Individual downloaders
# ---------------------------------------------------------------------------

def get_tiger_places() -> None:
    dest = DATA_DIR / "il_places_2023"
    marker = dest / "tl_2023_17_place.shp"
    if marker.exists():
        print(f"  [skip] TIGER Places already at {dest}")
        return
    dest.mkdir(parents=True, exist_ok=True)
    download_zip(TIGER_PLACES_URL, dest, "TIGER/Line 2023 IL Places")


def get_tiger_counties() -> None:
    dest = DATA_DIR / "il_counties_2023"
    if any(dest.glob("*.shp")):
        print(f"  [skip] TIGER Counties already at {dest}")
        return
    dest.mkdir(parents=True, exist_ok=True)
    download_zip(TIGER_COUNTY_URL, dest, "Census Cartographic IL Counties")


def get_senate_districts() -> None:
    dest = DATA_DIR / "senate_2020"
    if any(dest.glob("*.shp")):
        print(f"  [skip] Senate shapefile already at {dest}")
        return
    dest.mkdir(parents=True, exist_ok=True)

    print("  Attempting ILSBE senate download …")
    ok = _try_ilsbe(dest)
    if not ok:
        # Clean up any partial files before falling back
        for f in dest.iterdir():
            f.unlink()
        print("  Falling back to Census TIGER SLDU 2023 …")
        download_zip(TIGER_SLDU_URL, dest, "TIGER/Line 2023 IL SLDU (fallback)")
        print("  NOTE: Using Census TIGER SLDU — district column will be 'SLDUST'")
    else:
        print(f"  ILSBE senate downloaded to {dest}")


def _try_ilsbe(dest: Path) -> bool:
    for encoded in ILSBE_FILES:
        local_name = encoded.replace("%20", " ")
        url = ILSBE_BASE + encoded
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, timeout=60)
        except requests.RequestException as e:
            print(f"    Network error for {local_name}: {e}")
            return False

        if r.status_code != 200:
            print(f"    HTTP {r.status_code} for {local_name}")
            return False

        ct = r.headers.get("Content-Type", "")
        if "html" in ct.lower():
            print(f"    Received HTML instead of binary for {local_name}")
            return False

        path = dest / local_name
        path.write_bytes(r.content)

        if local_name.endswith(".shp") and not _valid_shp(path):
            print(f"    {local_name} failed magic-byte check")
            return False

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("=== TIGER Places ===")
    get_tiger_places()

    print("=== TIGER Counties ===")
    get_tiger_counties()

    print("=== Senate Districts ===")
    get_senate_districts()

    print("\nAll boundary data ready.")


if __name__ == "__main__":
    main()
