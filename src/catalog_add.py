"""EXPERIMENTAL: add tracks from the Apple Music catalog (not just your local
library) to already-created [Wrapped] playlists, closing the gap left by
create_playlists.py's misses.

Why this exists: Music.app's AppleScript dictionary has no documented verb
for "add this catalog track (by ID) to my library" - `duplicate <track> to
<playlist>` only works on tracks you already have a reference to (your local
library). So this drives the UI instead, via System Events: open a direct
link to the catalog track, then hunt the accessibility tree for something
that looks like an "Add" button and click it. Once (if) that lands the track
in your library, it re-runs create_playlists.py's own proven
library-search-and-add-to-playlist logic to do the actual playlist
placement - so only the "add to library" step relies on fragile UI
automation; getting it into the right playlist reuses code that's already
tested and working.

This was written with no macOS access to test against, so the UI-hunting
heuristic is a best guess, not a verified path. Expect it to need at least
one round of debugging. Two things make that debugging cheap instead of
painful:
  - --limit caps how many tracks it attempts, so you're not waiting through
    hundreds of failures before finding out it doesn't work.
  - --inspect dumps the real accessibility tree for one track to a file
    instead of attempting to click anything - if the heuristic click isn't
    working, send me that dump and I can target the actual UI precisely
    instead of guessing again.

Requires:
  - macOS, Music.app open and signed in to Apple Music
  - Accessibility permission for whatever runs this (Terminal, usually) -
    System Settings > Privacy & Security > Accessibility. macOS prompts for
    this automatically on first System Events use; approve it and re-run.
  - output/playlist_misses.json, written by a real (non-dry-run) run of
    create_playlists.py

Usage:
  python3 src/catalog_add.py --inspect
      # No clicking. Opens one track, dumps its accessibility tree to
      # output/catalog_add_inspect.txt. Run this first if the real attempt
      # below doesn't work.

  python3 src/catalog_add.py --profile "Fingerstyle Acoustic Folk" --limit 3
      # Try the real thing on just 3 tracks from one profile - sanity-check
      # before committing to a full run.

  python3 src/catalog_add.py
      # Every miss, every profile. Only run this once --limit 3 has worked.
"""
from __future__ import annotations  # str | None annotations need this on Python < 3.10

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from create_playlists import (
    as_escape,
    build_applescript,
    itunes_search,
    load_search_cache,
    normalize_title,
    run_applescript,
    save_search_cache,
)

ROOT = Path(__file__).resolve().parent.parent
MISSES_JSON_PATH = ROOT / "output" / "playlist_misses.json"
INSPECT_PATH = ROOT / "output" / "catalog_add_inspect.txt"
INSPECT_MENU_PATH = ROOT / "output" / "catalog_add_inspect_menu.txt"


def find_catalog_url(artist: str, title: str, cache: dict) -> str | None:
    """Best-match trackViewUrl from iTunes Search - exact artist match required.
    Prefers an exact (case-insensitive) title match over a normalize_title
    fuzzy match, since normalize_title deliberately collapses "Sex On Fire"
    and "Sex on Fire (Live)" together for discovery de-duplication - correct
    there, wrong here, where a fuzzy match could silently catalog-add a live
    or remix version instead of the one actually wanted."""
    try:
        results = itunes_search(f"{artist} {title}", cache, limit=10)
    except requests.exceptions.RequestException:
        return None
    artist_matches = [r for r in results if (r.get("artistName") or "").lower() == artist.lower()]
    for item in artist_matches:
        if (item.get("trackName") or "").lower() == title.lower():
            url = item.get("trackViewUrl")
            if url:
                return url
    target_key = normalize_title(title)
    for item in artist_matches:
        if normalize_title(item.get("trackName") or "") == target_key:
            url = item.get("trackViewUrl")
            if url:
                return url
    return None


INSPECT_SCRIPT = '''
tell application "Music"
    activate
    open location "{url}"
end tell
delay 4
tell application "System Events"
    tell process "Music"
        set out to ""
        try
            set frontWin to front window
            set allElements to entire contents of frontWin
            repeat with elem in allElements
                set elemRole to ""
                set elemName to ""
                set elemDesc to ""
                set elemHelp to ""
                try
                    set elemRole to (role of elem) as string
                end try
                try
                    set elemName to (name of elem) as string
                end try
                try
                    set elemDesc to (description of elem) as string
                end try
                try
                    set elemHelp to (help of elem) as string
                end try
                set out to out & elemRole & " | name=" & elemName & " | desc=" & elemDesc & " | help=" & elemHelp & linefeed
            end repeat
        on error errMsg
            set out to "ERROR: " & errMsg
        end try
        return out
    end tell
end tell
'''

# Adding via the toolbar's "Add to Library" adds the whole album, not just
# the one track - confirmed by inspecting the real album-page layout. The
# per-row "More" (•••) button should open a menu scoped to just that track,
# but its contents are unknown without real data, so this finds the target
# row (matched by exact track-title description) and clicks its More button,
# then dumps every menu-related element in the Music process - not just the
# window, since a popup menu isn't necessarily nested inside it - so the
# real menu item text/role can be read before attempting to click one.
INSPECT_MENU_SCRIPT = '''
tell application "Music"
    activate
    open location "{url}"
end tell
delay 4
tell application "System Events"
    tell process "Music"
        set foundRow to false
        set moreClicked to false
        try
            set allElements to entire contents of front window
            repeat with elem in allElements
                set elemRole to ""
                set elemDesc to ""
                try
                    set elemRole to (role of elem) as string
                end try
                try
                    set elemDesc to (description of elem) as string
                end try
                if not foundRow and elemDesc is "{title}" then
                    set foundRow to true
                end if
                if foundRow and not moreClicked and elemRole is "AXButton" and elemDesc is "More" then
                    click elem
                    set moreClicked to true
                    exit repeat
                end if
            end repeat
        on error errMsg
            return "ERROR finding/clicking row's More button: " & errMsg
        end try
        if not moreClicked then
            return "MORE_BUTTON_NOT_FOUND_FOR_ROW (row title match failed, or no More button after it)"
        end if
        delay 1
        set out to ""
        try
            set menuElements to entire contents of (process "Music")
            repeat with elem in menuElements
                set elemRole to ""
                set elemName to ""
                set elemDesc to ""
                try
                    set elemRole to (role of elem) as string
                end try
                if elemRole contains "Menu" then
                    try
                        set elemName to (name of elem) as string
                    end try
                    try
                        set elemDesc to (description of elem) as string
                    end try
                    set out to out & elemRole & " | name=" & elemName & " | desc=" & elemDesc & linefeed
                end if
            end repeat
        on error errMsg2
            set out to "ERROR dumping menu: " & errMsg2
        end try
        if out is "" then
            set out to "No menu-role elements found after clicking More - the menu may live outside the process's own tree, or the click didn't open one."
        end if
        return out
    end tell
end tell
'''

ADD_TO_LIBRARY_SCRIPT = '''
tell application "Music"
    activate
    open location "{url}"
end tell
delay 4
tell application "System Events"
    tell process "Music"
        try
            set frontWin to front window
            set allElements to entire contents of frontWin
            repeat with elem in allElements
                set elemRole to ""
                set elemDesc to ""
                try
                    set elemRole to (role of elem) as string
                end try
                try
                    set elemDesc to (description of elem) as string
                end try
                if elemRole is "AXButton" and (elemDesc is "Add to Library" or elemDesc is "Add") then
                    click elem
                    delay 1.5
                    return "CLICKED: " & elemDesc
                end if
            end repeat
            return "NOT_FOUND"
        on error errMsg
            return "ERROR: " & errMsg
        end try
    end tell
end tell
'''


def inspect_one(cache: dict, misses_by_profile: dict) -> None:
    for profile, misses in misses_by_profile.items():
        if not misses:
            continue
        artist, title = misses[0]
        print(f"Looking up catalog URL for: {artist} - {title}")
        url = find_catalog_url(artist, title, cache)
        if not url:
            print("Could not resolve a catalog URL for this track — trying the next one won't "
                  "help without network access; check your internet connection.")
            return
        print(f"Found: {url}")
        print("Opening in Music.app and dumping the accessibility tree (no clicking)...")
        script = INSPECT_SCRIPT.format(url=url)
        try:
            output = run_applescript(script)
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return
        INSPECT_PATH.write_text(output)
        print(f"Wrote {INSPECT_PATH} ({len(output.splitlines())} UI elements).")
        print("Send me that file's contents — I'll use it to target the real 'Add' control precisely.")
        return
    print("No misses found to inspect.")


def inspect_menu_one(cache: dict, misses_by_profile: dict) -> None:
    for profile, misses in misses_by_profile.items():
        if not misses:
            continue
        artist, title = misses[0]
        print(f"Looking up catalog URL for: {artist} - {title}")
        url = find_catalog_url(artist, title, cache)
        if not url:
            print("Could not resolve a catalog URL for this track.")
            return
        print(f"Found: {url}")
        print(f"Opening in Music.app, clicking the row's More button for '{title}', "
              f"and dumping any menu that appears (no further clicking)...")
        script = INSPECT_MENU_SCRIPT.format(url=url, title=as_escape(title))
        try:
            output = run_applescript(script)
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return
        INSPECT_MENU_PATH.write_text(output)
        print(f"Wrote {INSPECT_MENU_PATH} ({len(output.splitlines())} lines).")
        print("Send me that file's contents — I'll target the real per-track 'Add' menu item precisely.")
        return
    print("No misses found to inspect.")


def add_to_library(artist: str, title: str, url: str) -> str:
    script = ADD_TO_LIBRARY_SCRIPT.format(url=url)
    try:
        return run_applescript(script)
    except RuntimeError as e:
        return f"ERROR: {e}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", help="Only process this profile (by exact name).")
    parser.add_argument("--limit", type=int, default=None,
                         help="Cap how many misses to attempt (recommended: start with 3).")
    parser.add_argument("--inspect", action="store_true",
                         help="Dump the accessibility tree for one track instead of clicking anything.")
    parser.add_argument("--inspect-menu", action="store_true",
                         help="Click one track's row-level More button and dump the menu that "
                              "appears, instead of clicking further. Use this if you want only "
                              "the single track added, not its whole album.")
    args = parser.parse_args()

    if not MISSES_JSON_PATH.exists():
        print(f"{MISSES_JSON_PATH} not found — run a real (non-dry-run) "
              f"python3 src/create_playlists.py first.")
        return

    misses_by_profile = json.loads(MISSES_JSON_PATH.read_text())
    if args.profile:
        if args.profile not in misses_by_profile:
            print(f"No misses recorded for profile '{args.profile}'. "
                  f"Available: {', '.join(misses_by_profile)}")
            return
        misses_by_profile = {args.profile: misses_by_profile[args.profile]}

    cache = load_search_cache()

    if args.inspect:
        inspect_one(cache, misses_by_profile)
        save_search_cache(cache)
        return

    if args.inspect_menu:
        inspect_menu_one(cache, misses_by_profile)
        save_search_cache(cache)
        return

    for profile, misses in misses_by_profile.items():
        playlist_name = f"[Wrapped] {profile}"
        todo = misses[: args.limit] if args.limit else misses
        print(f"\n=== {profile} — attempting {len(todo)} of {len(misses)} misses ===")

        added_to_library: list[tuple[str, str]] = []
        for artist, title in todo:
            url = find_catalog_url(artist, title, cache)
            if not url:
                print(f"  [no catalog match] {artist} - {title}")
                continue
            result = add_to_library(artist, title, url)
            print(f"  {result} — {artist} - {title}")
            if result.startswith("CLICKED"):
                added_to_library.append((title, artist))
            time.sleep(1)

        if not added_to_library:
            print(f"  Nothing added to library for '{profile}' this pass.")
            continue

        print(f"  Attempted to library-add {len(added_to_library)} tracks — "
              f"now placing them into '{playlist_name}' via the proven library-search path...")
        script = build_applescript(playlist_name, added_to_library)
        # This profile's playlist already exists (misses only come from a real
        # run), so the "skip if exists" branch in build_applescript's script
        # would bail immediately - strip that guard for this follow-up pass by
        # rebuilding a version that assumes the playlist exists and just adds.
        script = script.replace(
            'if exists playlist playlistName then\n        return "SKIPPED_EXISTING_PLAYLIST"\n    end if\n    make new playlist with properties {name:playlistName}\n',
            "",
        )
        try:
            output = run_applescript(script)
            added = [l for l in output.splitlines() if l.startswith("ADDED: ")]
            print(f"  Placed {len(added)} of {len(added_to_library)} into '{playlist_name}'.")
        except RuntimeError as e:
            print(f"  ERROR placing tracks into playlist: {e}")

    save_search_cache(cache)


if __name__ == "__main__":
    main()
