"""Enrich track IDs with genre/artist metadata from the iTunes Lookup API.

Run locally (needs internet). Batches 100 IDs per request, ~20 requests/min
to stay under Apple's informal rate limits. Caches to data/track_meta.json
so it only ever runs once per track.

Usage: python3 src/enrich.py
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "track_meta.json"
LOOKUP = "https://itunes.apple.com/lookup?id={ids}&country=AU"


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "Apple_Music_-_Play_History_Daily_Tracks.csv", low_memory=False)
    ids = sorted(df["Track Identifier"].dropna().astype(int).unique())
    meta = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [i for i in ids if str(i) not in meta]
    print(f"{len(ids)} unique tracks, {len(todo)} to fetch")

    for n in range(0, len(todo), 100):
        batch = todo[n : n + 100]
        r = requests.get(LOOKUP.format(ids=",".join(map(str, batch))), timeout=30)
        r.raise_for_status()
        found = set()
        for item in r.json().get("results", []):
            tid = str(item.get("trackId", ""))
            if tid:
                found.add(tid)
                meta[tid] = {
                    "genre": item.get("primaryGenreName"),
                    "artist": item.get("artistName"),
                    "album": item.get("collectionName"),
                    "artwork": item.get("artworkUrl100"),
                    "duration_ms": item.get("trackTimeMillis"),
                    "release_date": item.get("releaseDate"),
                }
        for i in batch:  # mark misses so we don't refetch removed/regional tracks
            meta.setdefault(str(i), {"genre": None, "artist": None, "missing": True})
        CACHE.write_text(json.dumps(meta))
        print(f"  {n + len(batch)}/{len(todo)} done ({len(found)} found in batch)")
        time.sleep(3)

    print(f"Cached metadata for {len(meta)} tracks → {CACHE}")
    coverage_report(meta, df)


def coverage_report(meta: dict, df: pd.DataFrame) -> None:
    """Phase A step 1 deliverable: % of track IDs resolved, and a
    characterisation of the misses (which years/artists they belong to, as a
    proxy for "removed from catalogue" vs "regional" — older tracks with a
    disproportionate share of misses point at catalogue churn; misses spread
    evenly across years point more at regional/licensing gaps)."""
    ids = df["Track Identifier"].dropna().astype(int)
    unique_ids = ids.unique()
    total = len(unique_ids)
    missing_ids = {i for i in unique_ids if meta.get(str(i), {}).get("missing")}
    resolved = total - len(missing_ids)
    print(f"\n=== Coverage report ===")
    print(f"{resolved}/{total} track IDs resolved ({resolved / total * 100:.1f}%)")

    if not missing_ids:
        print("No misses — every track ID resolved.")
        return

    miss_rows = df[df["Track Identifier"].astype(int).isin(missing_ids)].copy()
    plays_missing = miss_rows["Play Count"].sum()
    total_plays = df["Play Count"].sum()
    print(f"{len(missing_ids)} missing IDs account for {plays_missing:,.0f} of "
          f"{total_plays:,.0f} raw plays ({plays_missing / total_plays * 100:.1f}%)")

    by_year = (
        miss_rows.assign(year=miss_rows["Date Played"].astype(str).str[:4])
        .groupby("year")["Play Count"].sum()
        .sort_index()
    )
    print("\nMissing plays by year (a skew toward earlier years suggests")
    print("catalogue removals; an even spread suggests regional/licensing gaps):")
    print(by_year.to_string())

    miss_rows["artist"] = miss_rows["Track Description"].str.split(" - ", n=1).str[0].str.strip()
    top_missing = miss_rows.groupby("artist")["Play Count"].sum().sort_values(ascending=False).head(15)
    print("\nTop missing artists by play count:")
    print(top_missing.to_string())


if __name__ == "__main__":
    main()
