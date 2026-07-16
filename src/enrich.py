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
                }
        for i in batch:  # mark misses so we don't refetch removed/regional tracks
            meta.setdefault(str(i), {"genre": None, "artist": None, "missing": True})
        CACHE.write_text(json.dumps(meta))
        print(f"  {n + len(batch)}/{len(todo)} done ({len(found)} found in batch)")
        time.sleep(3)

    print(f"Cached metadata for {len(meta)} tracks → {CACHE}")


if __name__ == "__main__":
    main()
