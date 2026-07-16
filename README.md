# Music Wrapped — Apple Music lifetime analysis

Analyses the Apple privacy export (`Play History Daily Tracks.csv`, new format,
2016–2026) to produce Spotify Wrapped–style stats and, later, taste extraction
for playlist generation.

## Data facts (verified against this export)
- 95,290 rows, one per track per day. All `Track Identifier` values are real
  Apple Music catalogue IDs (no local IDs) — enrichment is a direct lookup.
- `Hours` column is a comma-separated list of **UTC** hour buckets. Convert
  with `timezone_offset_hours` in config.yaml (AWST = +8).
- ~80% of raw plays are sleep/ambient audio on the HomePod, plus a small
  amount of UCB 2 radio that is not the account owner's listening. Both are
  filtered — see config.yaml.

## Pipeline
1. `python3 src/enrich.py` — one-off iTunes Lookup pass over ~8,300 track IDs
   (~10 min, cached to `data/track_meta.json`). Requires internet.
2. `python3 run_wrapped.py` — filtered Wrapped report to `output/`.

## Filtering
- `blocked_artists` in config.yaml: exact-match removals (currently `UCB 2`).
- Sleep filter: behavioural (≥80% of plays 8pm–6am local AND ≥80% HomePod,
  min 20 plays) plus keyword match. After enrichment, `excluded_genres`
  (Sleep, New Age, Ambient) becomes the authoritative filter and catches the
  daytime-ambient residuals the behavioural filter misses.

## Next phases
- **Wrapped UI**: swipeable year cards (port stats to SwiftUI).
- **Taste extraction**: profile from filtered plays (genre/era clusters,
  completion vs skip, time-of-day) → Claude API characterisation → candidate
  tracks via MusicKit catalogue search.
- **Playlist creation**: MusicKit `MusicLibrary.shared` (iOS 16+), needs
  Apple Developer Program membership.
