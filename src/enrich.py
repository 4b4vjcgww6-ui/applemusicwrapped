"""Enrich track IDs with genre/artist metadata from the iTunes Lookup API.

Run locally (needs internet). Batches 100 IDs per request, ~20 requests/min
to stay under Apple's informal rate limits. Caches to data/track_meta.json
so it only ever runs once per track.

A large share of track IDs fail direct Lookup not because the song has
left the catalogue, but because Apple re-catalogues music constantly
(remasters, re-distributions, reissues) - the same song accumulates
multiple Track Identifiers over the years, and old plays stay recorded
against IDs that are no longer the "live" one. Confirmed against a real
listening history: Elton John's "Tiny Dancer" alone had 5 distinct Track
Identifiers, OneRepublic's "All the Right Moves" had 5, Charlie
Cunningham's "Permanent Way" had 3. So after the ID-based pass, this
retries every still-missing ID via an artist+title text search instead
(matching on exact artist + normalized title) - much better coverage for
exactly the heavily-replayed favourites that matter most for taste
profiling. That fallback pass re-examines the *entire* current cache's
missing entries, not just ones fetched this run, so re-running this
script retroactively improves an existing data/track_meta.json.

Usage:
  python3 src/enrich.py               # ID lookup + title-search fallback
  python3 src/enrich.py --no-fallback # ID lookup only (faster, lower coverage)
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import normalize_title

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "track_meta.json"
LOOKUP = "https://itunes.apple.com/lookup?id={ids}&country=AU"
SEARCH_URL = "https://itunes.apple.com/search"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-fallback", action="store_true",
        help="Skip the title-search fallback for IDs that fail direct lookup "
             "(faster, ~10-25%% lower coverage based on real-world testing).",
    )
    args = parser.parse_args()

    df = pd.read_csv(ROOT / "data" / "Apple_Music_-_Play_History_Daily_Tracks.csv", low_memory=False)
    ids = sorted(df["Track Identifier"].dropna().astype(int).unique())
    meta = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [i for i in ids if str(i) not in meta]
    print(f"{len(ids)} unique tracks, {len(todo)} to fetch by ID")

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
        for i in batch:  # mark misses so a title-fallback pass (or a rerun) can retry them
            meta.setdefault(str(i), {"genre": None, "artist": None, "missing": True})
        CACHE.write_text(json.dumps(meta))
        print(f"  {n + len(batch)}/{len(todo)} done ({len(found)} found in batch)")
        time.sleep(3)

    print(f"Cached metadata for {len(meta)} tracks → {CACHE}")

    if not args.no_fallback:
        resolve_via_title_fallback(meta, df)

    coverage_report(meta, df)


def resolve_via_title_fallback(meta: dict, df: pd.DataFrame) -> None:
    id_to_artist_title = (
        df.dropna(subset=["Track Identifier"])
        .assign(
            tid=lambda d: d["Track Identifier"].astype(int),
            artist=lambda d: d["Track Description"].str.split(" - ", n=1).str[0].str.strip(),
            title=lambda d: d["Track Description"].str.split(" - ", n=1).str[1],
        )
        .drop_duplicates("tid")
        .set_index("tid")[["artist", "title"]]
    )

    missing_ids = [int(k) for k, v in meta.items() if v.get("missing")]
    if not missing_ids:
        return
    print(f"\nRetrying {len(missing_ids)} misses via artist+title search "
          f"(not ID lookup) - ~1 request/sec, so this takes a while...")

    resolved = 0
    for i, tid in enumerate(missing_ids, 1):
        if tid not in id_to_artist_title.index:
            continue
        row = id_to_artist_title.loc[tid]
        artist, title = row["artist"], row["title"]
        if not artist or not isinstance(title, str):
            continue

        try:
            r = requests.get(
                SEARCH_URL,
                params={"term": f"{artist} {title}", "entity": "song", "limit": 5, "country": "AU"},
                timeout=30,
            )
            r.raise_for_status()
            results = r.json().get("results", [])
        except requests.exceptions.RequestException:
            results = []

        for item in results:
            if (
                (item.get("artistName") or "").lower() == artist.lower()
                and normalize_title(item.get("trackName") or "") == normalize_title(title)
            ):
                meta[str(tid)] = {
                    "genre": item.get("primaryGenreName"),
                    "artist": item.get("artistName"),
                    "album": item.get("collectionName"),
                    "artwork": item.get("artworkUrl100"),
                    "duration_ms": item.get("trackTimeMillis"),
                    "release_date": item.get("releaseDate"),
                    "resolved_via": "title_fallback",
                }
                resolved += 1
                break

        if i % 50 == 0:
            CACHE.write_text(json.dumps(meta))
            print(f"  {i}/{len(missing_ids)} retried, {resolved} resolved so far")
        time.sleep(1)

    CACHE.write_text(json.dumps(meta))
    print(f"Title-search fallback resolved {resolved}/{len(missing_ids)} previously-missing tracks.")


def coverage_report(meta: dict, df: pd.DataFrame) -> None:
    """Phase A step 1 deliverable: % of track IDs resolved, and a
    characterisation of the misses (which years/artists they belong to)."""
    ids = df["Track Identifier"].dropna().astype(int)
    unique_ids = ids.unique()
    total = len(unique_ids)
    missing_ids = {i for i in unique_ids if meta.get(str(i), {}).get("missing")}
    resolved = total - len(missing_ids)
    via_fallback = sum(1 for v in meta.values() if v.get("resolved_via") == "title_fallback")
    print(f"\n=== Coverage report ===")
    print(f"{resolved}/{total} track IDs resolved ({resolved / total * 100:.1f}%)"
          + (f", {via_fallback} of those via title-search fallback" if via_fallback else ""))

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
    print("\nMissing plays by year:")
    print(by_year.to_string())

    miss_rows["artist"] = miss_rows["Track Description"].str.split(" - ", n=1).str[0].str.strip()
    top_missing = miss_rows.groupby("artist")["Play Count"].sum().sort_values(ascending=False).head(15)
    print("\nTop missing artists by play count (a genuinely obscure/ambient name here is")
    print("expected noise; a mainstream artist means the title-fallback pass still couldn't")
    print("match it - usually a stylised title, a live/session variant, or a feature credit):")
    print(top_missing.to_string())


if __name__ == "__main__":
    main()
