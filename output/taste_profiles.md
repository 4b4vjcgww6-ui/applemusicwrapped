# Taste profiles — lifetime listening, 2016–2026

Built from `output/taste_profile.json` (515 core artists, 40 phase artists,
out of 2,305 with any real plays, from the 15,823-play filtered dataset —
846 hours across 11 years).

**Update, cross-checked against real genre data**: `enrich.py` has now run
(locally, with real internet access) and the genre labels below have been
checked against actual iTunes genre tags. The headline result: **no seed
artist in any of the six profiles came back flagged as ambient/sleep
residual** — the clusters hold up. But iTunes' genre taxonomy is coarser
than my style labels (mostly `Alternative`/`Pop`/`Rock`/`Dance`/`R&B/Soul`,
no `Britpop` or `fingerstyle` categories exist at all), so treat the profile
*names* below as style descriptors, not genre matches — that was always the
intent, but now it's confirmed rather than assumed. Specific corrections:

- **Illy** is tagged `Hip-Hop`, not close to the rest of the "Aussie
  Singer-Songwriter" cluster (`Alternative`/`Pop`/`Singer/Songwriter`) — that
  profile is really "artists you follow because they're Australian," not a
  genre-consistent cluster. Worth knowing if you want genre-tighter
  playlists later.
- **The Weeknd** is `R&B/Soul`, not `Pop` — same story for "2010s Mainstream
  Pop": it's an era/chart-mainstream grouping, not a genre-pure one.
- No Oasis/Ocean Colour Scene/Coldplay/Keane track came back tagged
  `Britpop` — iTunes doesn't use that category for any of them (Oasis is
  `Indie Rock`, Ocean Colour Scene and The Verve are both `Pop`). The
  "anthemic Brit-alt" label was a style call, not something iTunes' taxonomy
  would ever produce on its own.
- **The Franklin Electric** and **Capital Cities** — both seed artists in
  their respective profiles — came back with no genre at all (a real
  coverage gap in enrichment, not a misclassification).
- The Christmas-genre pipeline bug (it was checking for `genre == "Holiday"`,
  but iTunes actually uses `"Christmas"` and several `"Christmas: *"`
  subtypes) has been fixed in `src/pipeline.py` — re-run `run_wrapped.py` to
  pick up the extra reclassified plays.

Everything below is otherwise unchanged from the original draft — every
artist/track/number cited was already real, pulled from your actual play
data.

"Core" = spread across ≥3 calendar years with no single year holding more
than 60% of that artist's plays (sustained interest). "Phase" = a
concentrated burst, ≥15 plays, that hasn't (yet, or won't) spread that way.
Weighted plays = raw plays × engagement quality (average of skip-based
completion rate and the share of listens that ended in `NATURAL_END_OF_TRACK`
rather than a skip/pause/switch) — so a well-loved 100-play artist can
outrank a half-skipped 150-play one.

One exclusion up front: **Personal Effects** technically classifies as
"core" (30 plays, 3 years, 100% completion) but its own top track is titled
*Rejuvenation (Sleep)* — this is almost certainly ambient/sleep content that
slipped past the behavioural filters the same way the flagged
`likely_ambient_residual` cluster did (see bottom of this file). Excluded
from every profile below.

---

## 1. Fingerstyle acoustic folk

Your single most-listened artist of all time, by a wide margin, sits here.

- **Charlie Cunningham** — 527 plays, 401.6 weighted, 9 years (2018–2026),
  79.3% completion. *Permanent Way* (135 plays), *Headlights* (90),
  *Minimum* (82), *Sink In* (53). Nobody else is close to this — more than
  double the #2 artist lifetime.
- **Nick Mulvey** — 123 plays, 9 years. *Meet Me There* (46), *Fever to the
  Form* (23) — another fingerstyle guitarist, same lineage as Cunningham.
- **Roo Panes** — 61 plays, almost entirely one track: *Tiger Striped Sky*
  (53 of 61 plays).
- **José González** — 36 plays, 8 years, 86.1% completion. *Heartbeats*
  (21).
- **The Franklin Electric** — 57 plays. *Strongest Man Alive* (42 of 57).
- **#1 Dads** — 39 plays, almost a single-track obsession: *Freedom
  Fighter* (38 of 39).
- Also in this pocket: **Jack Savoretti**, **Hollow Coves**, **Sons Of
  The East** — gentle, acoustic-led, melodic.

This is the clearest, most sustained thread in the whole dataset — quiet
fingerpicked guitar songwriters, revisited for years rather than months.

## 2. Anthemic Brit/Irish alt-rock

The 2000s–2010s UK stadium-indie lineage — Coldplay is your #2 lifetime
artist.

- **Coldplay** — 249 plays, 186.0 weighted, 11 years. *Lost!* (35), *The
  Hardest Part* (29).
- **Keane** — 142 plays, 11 years, 84.5% completion. *Somewhere Only We
  Know* (52 of 142 — over a third of all Keane plays on one song).
- **Snow Patrol** — 132 plays, 11 years, 84.1% completion.
- **Bastille** — 145 plays. *Pompeii* (44), *Laura Palmer* (41).
- **The Verve** — 59 plays, almost monogamous with one song: *Bitter Sweet
  Symphony* (53 of 59).
- **Kodaline**, **The Script**, **Feeder**, **You Me At Six**, **Kaiser
  Chiefs**, **James Bay**, **Mumford & Sons**, **Gerry Cinnamon** round out
  the same emotional register.
- **Recent addition, 2025–26**: **Oasis** was your #1 artist of both 2025
  (33 plays) and 2026-to-date (19 plays), joined by **Ocean Colour Scene**
  (15 plays, first played Dec 2025) — a fresh Britpop-nostalgia layer on
  top of the older Coldplay/Keane core, concentrated in the last ~8 months
  of the data.

## 3. Australian singer-songwriter / indie

The "home team" — distinctly AU/NZ artists you've followed consistently.

- **The Rubens** — 212 plays, 165.4 weighted, 7 years. *Masterpiece* (67),
  *Live In Life* (54).
- **Vance Joy** — 156 plays, 10 years. *Georgia* (44), *Riptide* (30).
- **Harrison Storm** — 130 plays, 8 years. *Run* (58 of 130).
- **Amy Shark** — 101 plays, 11 years, **highest completion rate of any
  core artist at 92.1%** — when Amy Shark comes on, you don't skip it.
- **Illy** — 106 plays, 10 years. *Papercuts* (43), *Catch 22* (39).
- **Gang of Youths** — 79 plays, though only 5 years (a slightly younger
  addition than the rest of this group).
- **Dean Lewis**, **Birds of Tokyo**, **Sons Of The East** also sit here.

## 4. Classic & legacy rock/pop

Catalogue-diving through decades-old material — these show the widest
skip/exploration behaviour of any cluster, which fits: you're often
sampling a back catalogue rather than looping a favourite.

- **Fleetwood Mac** — 180 plays, 8 years. *Everywhere* (52); several
  "Remastered"/reissue tagged tracks, consistent with reissue-era
  streaming.
- **Elton John** — 165 plays but the **lowest completion rate in the top
  20 at 64.8%** — heavy browsing through a huge catalogue rather than
  repeat-listening a handful of songs.
- **Matchbox Twenty** — 105 plays, 11 years.
- **Oasis** — 94 plays lifetime, but concentrated recently (see #2 above —
  it's really a 2025–26 phenomenon wearing an 11-year core label because
  of scattered earlier plays).
- **Madonna**, **ABBA**, **Kate Bush**, **Green Day** — same "dip into a
  well-known catalogue" pattern.

## 5. 2010s mainstream pop / dance-pop

- **The Weeknd** — 109 plays, 10 years. *Blinding Lights* (52).
- **The Chainsmokers** — 106 plays. **Kygo** — 98 plays, *Fiction* (41).
- **Ariana Grande** — 84 plays, almost all one track: *no tears left to
  cry* (61 of 84).
- **Taylor Swift** — 55 plays but **92.7% completion**, among the highest
  of any core artist.
- **Dua Lipa**, **Calvin Harris**, **Avicii**, **Katy Perry**, **Sia**,
  **Justin Bieber**, **Shawn Mendes** — mainstream chart pop and
  festival-EDM crossovers, engaged with lightly but consistently for a
  decade.

## 6. Atmospheric synth-pop / dream-pop indie

Glossier, more production-forward than the acoustic-folk cluster, and
distinguished from the anthemic Brit-alt cluster by a synth/electronic
palette. Notably, this is the cluster with the **most extreme single-track
skew** — several of these "artists" are really one song on repeat:

- **The Neighbourhood** — 70 plays, **68 of them** on *Sweater Weather*.
- **Glass Animals** — 66 plays, 57 on *Heat Waves* (the 2020–21 viral era).
- **Future Islands** — 78 plays, 56 on *Seasons (Waiting On You)*.
- **Empire Of The Sun**, **Foster the People**, **Young the Giant**,
  **Milky Chance**, **St. Lucia**, **Years & Years**, **The Temper Trap**,
  **Capital Cities**, **The 1975** — same lane: warm synths, a hooky
  chorus, played hard for a stretch.

---

## Phases — concentrated bursts, not (yet) sustained taste

**Spring 2019 melodic-house / DJ-mix binge.** A tight cluster of tracks —
**Art Wilson** (*Rebecca's Theme (Water) [MIXED]*, 31 plays), **Lisbon
Kid** (*Sunburst (Alternative Version) [MIXED]*, 25 plays), **Micko
Roche** (*Baltimore (Afterlife Remix) [MIXED]*, 22 plays), **Chris Coco &
Afterlife** (19 plays), **Pete Tong, The Heritage Orchestra & Jules
Buckley** (28 plays) — all first played within days of each other in
March–June 2019, single-track artists, "[MIXED]" tagging pointing to a
specific compilation or radio mix rather than individually-discovered
acts. A genuine, dateable three-month phase rather than ongoing taste —
distinct from the six core profiles above.

**Currently emerging, not yet proven** — recent arrivals with real plays
but too little history to call sustained: **A R I Z O N A** (53 plays
across 7 years but concentrated), **LPX** (33 plays), **Ocean Colour
Scene** (part of the Britpop-nostalgia note above), **sombr** and
**Ladyhawke** (both recent 2025–26 discoveries — flagged separately below
as needing a skip-rate sanity check, not because they look fake, but
because they're too new to classify confidently either way).

---

## Excluded — flagged as likely non-taste (ambient/sleep residual)

`src/taste.py` flags artists whose play pattern (near-zero skip rate, high
plays-per-track, short/concentrated window) resembles the sleep/focus
content the behavioural filters already remove — but these specific ones
sat just below the `config.yaml` thresholds. Not removed from the pipeline
(that's genre enrichment's job, per README), but excluded from every
profile above:

- **Crystalline Cove, Soleane, Waves Eternal, Big Sky Blue, Lenire** — five
  differently-named "artists" that play on **identical recurring dates in
  lockstep** (2024-12-26, 2025-01-14, 02-05/06, 04-17/19, 06-02/06,
  07-20/24, 09-23/24, 10-24/26, 12-27, 2026-03-13/14), evening/late-night
  hours, near-zero skips — clearly one ambient/wind-down playlist, not five
  discoveries.
- **chamberecho** — 53 plays in a single 2-day window, skip rate 0.0377
  (just over the focus filter's 0.03 cutoff).
- **Aerial Love** — 16 plays, 100% concentrated in a 2.5-week window.

These will very likely resolve to Sleep/Ambient/New Age genre tags once
`enrich.py` runs, at which point `excluded_genres` in `config.yaml` removes
them from `run_wrapped.py`'s output automatically — no manual list needed.
