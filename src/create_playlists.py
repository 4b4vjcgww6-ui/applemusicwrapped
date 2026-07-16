"""Generate candidate tracks per taste profile and create them as playlists
in Music.app, via AppleScript (osascript).

Requires macOS with Music.app signed into your Apple Music account, and
internet access for the iTunes Search API discovery step. Cannot run inside
this session's Linux container — write locally and run on your Mac.

For each profile in config.yaml's taste_playlists.profiles:
  1. Build a "spine" of proven favourites from your own filtered play
     history (high completion, sustained plays) for that profile's seed
     artists.
  2. Fill the rest with discovery candidates from the iTunes Search API
     (free, no auth): deeper cuts from the same seed artists, plus tracks
     from other artists sharing a genre with those seed artists.
  3. Exclude anything matching a sleep/focus/blocked artist, a Christmas
     keyword, or the likely_ambient_residual flag from taste_profile.json.
  4. Create "[Wrapped] <profile name>" in Music.app if it doesn't already
     exist. If it does, skip entirely — never touch an existing playlist,
     wrapped-generated or otherwise. Search your local library for each
     candidate by name+artist; add matches, log misses (mostly discovery
     tracks you don't own yet) to output/playlist_creation_log.md for
     manual review.

Usage:
  python3 src/create_playlists.py            # full run: fetch + create playlists
  python3 src/create_playlists.py --dry-run  # build candidate lists, print
                                              # what would happen, touch
                                              # nothing in Music.app
  python3 src/create_playlists.py --no-discovery  # spine only, skip iTunes
                                                   # Search API (e.g. no
                                                   # internet right now)
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import apply_filters, load_config, load_history, normalize_title

ROOT = Path(__file__).resolve().parent.parent
SEARCH_CACHE_PATH = ROOT / "data" / "itunes_search_cache.json"
TASTE_PROFILE_PATH = ROOT / "output" / "taste_profile.json"
LOG_PATH = ROOT / "output" / "playlist_creation_log.md"
SEARCH_URL = "https://itunes.apple.com/search"

# Broad top-level iTunes genres: searching these as a bare text query returns
# generic current chart hits rather than anything taxonomically related, so
# they're excluded from the related-artist discovery step (see build_discovery).
GENERIC_GENRES = {
    "Pop", "Alternative", "Rock", "Dance", "Electronic", "R&B/Soul",
    "Hip-Hop/Rap", "Hip-Hop", "Dance/Electronic",
}


# ---------------------------------------------------------------- candidates

def load_exclusions(cfg: dict, audit: dict) -> tuple[set[str], set[str]]:
    """(excluded_artists, christmas_title_keywords) — used to keep discovery
    candidates out of sleep/focus/blocked/Christmas territory, since they
    come from iTunes, not from your own already-filtered play history."""
    excluded_artists = (
        set(audit["sleep_artists_list"])
        | set(audit["focus_artists"])
        | set(cfg["blocked_artists"])
    )
    try:
        residual = json.loads(TASTE_PROFILE_PATH.read_text())
        excluded_artists |= {
            a["artist"] for a in residual["artists"] if a.get("likely_ambient_residual")
        }
    except FileNotFoundError:
        print("Warning: output/taste_profile.json not found — run src/taste.py "
              "first for the likely_ambient_residual exclusion. Continuing "
              "without it.")
    return excluded_artists, set(cfg["christmas_filter"]["keywords"])


def is_christmas_titled(title: str, keywords: set[str]) -> bool:
    kw = "|".join(re.escape(k) for k in keywords)
    return bool(re.search(kw, title, re.IGNORECASE))


def build_spine(clean: pd.DataFrame, seed_artists: list[str], target: int, max_per_artist: int) -> list[tuple[str, str]]:
    pool = clean[clean["artist"].isin(seed_artists) & (clean["Play Count"] > 0)]
    t = pool.groupby(["artist", "title"]).agg(
        plays=("Play Count", "sum"), skips=("Skip Count", "sum")
    ).reset_index()
    t["completion_rate"] = (1 - t.skips / t.plays).clip(lower=0, upper=1)
    t["weighted"] = t.plays * t.completion_rate
    t = t.sort_values("weighted", ascending=False)

    spine: list[tuple[str, str]] = []
    per_artist_count: dict[str, int] = {}
    for row in t.itertuples():
        if len(spine) >= target:
            break
        if per_artist_count.get(row.artist, 0) >= max_per_artist:
            continue
        spine.append((row.title, row.artist))
        per_artist_count[row.artist] = per_artist_count.get(row.artist, 0) + 1
    return spine


def load_search_cache() -> dict:
    if SEARCH_CACHE_PATH.exists():
        return json.loads(SEARCH_CACHE_PATH.read_text())
    return {}


def save_search_cache(cache: dict) -> None:
    SEARCH_CACHE_PATH.write_text(json.dumps(cache))


def itunes_search(term: str, cache: dict, limit: int = 25) -> list[dict]:
    key = f"song|{term}|{limit}"
    if key in cache:
        return cache[key]
    params = {"term": term, "entity": "song", "limit": limit, "country": "AU"}
    r = requests.get(SEARCH_URL, params=params, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])
    cache[key] = results
    time.sleep(1)
    return results


def build_discovery(
    seed_artists: list[str],
    spine_keys: set[str],
    excluded_artists: set[str],
    christmas_keywords: set[str],
    target: int,
    cache: dict,
    used_related_keys: set[str],
) -> list[tuple[str, str]]:
    seen_keys = set(spine_keys)
    seed_lower = {a.lower() for a in seed_artists}
    deeper_cuts: list[tuple[str, str]] = []
    genre_votes: dict[str, int] = {}

    for artist in seed_artists:
        try:
            results = itunes_search(artist, cache, limit=200)  # iTunes Search API's documented max
        except requests.exceptions.RequestException as e:
            print(f"  iTunes Search failed for '{artist}': {e}")
            continue
        for item in results:
            item_artist = (item.get("artistName") or "")
            if item_artist.lower() != artist.lower():
                continue
            title = item.get("trackName") or ""
            key = normalize_title(title)
            if not title or key in seen_keys:
                continue
            if is_christmas_titled(title, christmas_keywords):
                continue
            genre = item.get("primaryGenreName")
            if genre:
                genre_votes[genre] = genre_votes.get(genre, 0) + 1
            seen_keys.add(key)
            deeper_cuts.append((title, item_artist))

    # Related-via-genre: searching a bare genre name works as a plain-text
    # query, not a taxonomy filter - broad genres just return generic current
    # chart hits, identically, regardless of which profile asked. Excluding
    # the broadest (GENERIC_GENRES) helps, but even a narrower-sounding genre
    # like "Singer/Songwriter" can still collapse to the same "canonical
    # greatest hits" result for any profile that lands on it (confirmed
    # against real output - three unrelated profiles all got the identical
    # Paul Simon/Olafur Arnalds/LP block from that exact genre). The real
    # fix is this: used_related_keys is shared across every profile in this
    # run, so once a candidate has been used as a "related" pick for one
    # profile, no later profile can reuse it - whatever the cause, a repeat
    # is never actually profile-specific "related" content. Profiles
    # processed earlier (see config.yaml's profile order) get first claim;
    # later ones fall back to more deeper cuts instead, which is a better
    # trade than a duplicate.
    related: list[tuple[str, str]] = []
    specific_genres = [g for g in genre_votes if g not in GENERIC_GENRES]
    if specific_genres:
        top_genres = sorted(specific_genres, key=genre_votes.get, reverse=True)[:3]
        for genre in top_genres:
            try:
                results = itunes_search(genre, cache, limit=100)
            except requests.exceptions.RequestException as e:
                print(f"  iTunes Search failed for genre '{genre}': {e}")
                continue
            for item in results:
                item_artist = item.get("artistName") or ""
                if item_artist.lower() in seed_lower or item_artist in excluded_artists:
                    continue
                title = item.get("trackName") or ""
                key = normalize_title(title)
                if not title or key in seen_keys or key in used_related_keys:
                    continue
                if is_christmas_titled(title, christmas_keywords):
                    continue
                seen_keys.add(key)
                used_related_keys.add(key)
                related.append((title, item_artist))

    # Deeper cuts are the reliable half - same proven artists, always
    # relevant. Related-genre picks are more speculative and sometimes
    # unavailable (no specific-enough genre this round); when that happens,
    # deeper cuts backfill the rest of the target instead of leaving slots
    # empty.
    related_slice = related[: int(target * 0.4) + 1]
    deeper_slice = deeper_cuts[: target - len(related_slice)]
    combined = deeper_slice + related_slice
    return [
        (t, a) for t, a in combined
        if a not in excluded_artists
    ][:target]


# ---------------------------------------------------------------- AppleScript

def as_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_applescript(playlist_name: str, tracks: list[tuple[str, str]]) -> str:
    track_literal = ", ".join(
        f'{{"{as_escape(title)}", "{as_escape(artist)}"}}' for title, artist in tracks
    )
    return f'''
tell application "Music"
    set playlistName to "{as_escape(playlist_name)}"
    if exists playlist playlistName then
        return "SKIPPED_EXISTING_PLAYLIST"
    end if
    make new playlist with properties {{name:playlistName}}
    set thePlaylist to playlist playlistName
    set trackList to {{{track_literal}}}
    set resultLines to {{"CREATED_PLAYLIST"}}
    repeat with pair in trackList
        set trackTitle to item 1 of pair
        set artistName to item 2 of pair
        try
            set matches to (every track of library playlist 1 whose name contains trackTitle and artist contains artistName)
        on error
            set matches to {{}}
        end try
        if (count of matches) > 0 then
            duplicate (item 1 of matches) to thePlaylist
            set end of resultLines to "ADDED: " & artistName & " - " & trackTitle
        else
            set end of resultLines to "MISS: " & artistName & " - " & trackTitle
        end if
    end repeat
    set AppleScript's text item delimiters to linefeed
    set resultText to resultLines as text
    set AppleScript's text item delimiters to ""
    return resultText
end tell
'''


def run_applescript(script: str) -> str:
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            "osascript not found — this only runs on macOS with Music.app "
            "installed. Use --dry-run to preview candidate lists anywhere else."
        )
    if proc.returncode != 0:
        raise RuntimeError(f"osascript failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


# ---------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="Build candidate lists and print them; never call osascript.")
    parser.add_argument("--no-discovery", action="store_true",
                         help="Skip the iTunes Search API step; spine-only playlists.")
    args = parser.parse_args()

    cfg = load_config()
    tp_cfg = cfg["taste_playlists"]
    raw = load_history(cfg)
    clean, audit, christmas = apply_filters(raw, cfg)
    excluded_artists, christmas_keywords = load_exclusions(cfg, audit)

    cache = load_search_cache()
    log_lines = ["# Playlist creation log\n"]
    used_related_keys: set[str] = set()

    for profile in tp_cfg["profiles"]:
        name = profile["name"]
        seed_artists = [a for a in profile["seed_artists"] if a not in excluded_artists]
        print(f"\n=== {name} ===")

        spine = build_spine(clean, seed_artists, tp_cfg["spine_target"], tp_cfg["max_tracks_per_seed_artist"])
        spine_keys = {normalize_title(t) for t, _ in spine}
        print(f"  Spine: {len(spine)} tracks")

        discovery: list[tuple[str, str]] = []
        if not args.no_discovery:
            remaining = tp_cfg["candidates_per_playlist"] - len(spine)
            discovery = build_discovery(
                seed_artists, spine_keys, excluded_artists, christmas_keywords, remaining, cache,
                used_related_keys,
            )
            print(f"  Discovery: {len(discovery)} tracks")
        else:
            print("  Discovery: skipped (--no-discovery)")

        candidates = spine + discovery
        log_lines.append(f"\n## {name}\n")
        log_lines.append(f"Seed artists: {', '.join(seed_artists)}\n")
        log_lines.append(f"Candidates: {len(candidates)} ({len(spine)} spine, {len(discovery)} discovery)\n")

        if args.dry_run:
            log_lines.append("\n**Dry run — playlist not created.**\n")
            for title, artist in candidates:
                log_lines.append(f"- {artist} — {title}")
            print(f"  [dry-run] would create '[Wrapped] {name}' with {len(candidates)} candidates")
            continue

        playlist_name = f"[Wrapped] {name}"
        script = build_applescript(playlist_name, candidates)
        try:
            output = run_applescript(script)
        except RuntimeError as e:
            log_lines.append(f"\n**AppleScript error — playlist not created: {e}**\n")
            print(f"  ERROR: {e}")
            continue

        result_lines = output.splitlines()
        if result_lines and result_lines[0] == "SKIPPED_EXISTING_PLAYLIST":
            log_lines.append(f"\n**Playlist '{playlist_name}' already exists — skipped, untouched.**\n")
            print(f"  Skipped: '{playlist_name}' already exists")
            continue

        added = [l for l in result_lines if l.startswith("ADDED: ")]
        misses = [l for l in result_lines if l.startswith("MISS: ")]
        log_lines.append(f"\nCreated '{playlist_name}': {len(added)} added, {len(misses)} misses.\n")
        if misses:
            log_lines.append("\n**Misses (not in your local library — add manually if wanted):**\n")
            for m in misses:
                log_lines.append(f"- {m[len('MISS: '):]}")
        print(f"  Created '{playlist_name}': {len(added)} added, {len(misses)} misses")

    save_search_cache(cache)
    LOG_PATH.write_text("\n".join(log_lines))
    print(f"\nWrote {LOG_PATH}")


if __name__ == "__main__":
    main()
