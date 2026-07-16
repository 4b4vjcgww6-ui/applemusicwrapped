"""Run the full Wrapped analysis and write output/wrapped_report.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from pipeline import (
    apply_filters,
    apply_genre_layer,
    genre_stats,
    load_config,
    load_history,
    load_track_meta,
    wrapped_stats,
)

cfg = load_config()
df = load_history(cfg)
clean, audit, christmas = apply_filters(df, cfg)

meta = load_track_meta()
genre_audit = {}
if meta:
    clean, christmas, genre_audit = apply_genre_layer(clean, christmas, cfg, meta)

stats = wrapped_stats(clean, cfg["report"]["top_n"])

lines = ["# Lifetime Wrapped — filtered\n"]
lines.append(f"**Filter audit:** removed {audit['sleep_plays_removed']:,} sleep plays "
             f"({audit['sleep_artists']} artists), {audit['focus_plays_removed']:,} focus-music plays ({len(audit['focus_artists'])} artists) and {audit['blocked_plays_removed']:,} blocked-artist plays. "
             f"Remaining: {audit['plays_remaining']:,} plays, ~{audit['hours_remaining']:,} hours. "
             f"Christmas plays held separately: {audit['christmas_plays']:,}.\n")

if meta:
    lines.append(
        f"\n**Genre filter (post-enrichment layer):** removed a further "
        f"{genre_audit['genre_excluded_plays']:,} plays across "
        f"{genre_audit['genre_excluded_artist_count']} artists that behavioural "
        f"filters missed ({', '.join(f'{g}: {p:,}' for g, p in genre_audit['genre_excluded_by_genre'].items())}). "
        f"Reclassified a further {genre_audit['holiday_reclassified_plays']:,} "
        f"Holiday-genre plays from general listening into the Christmas corner.\n"
    )
    if genre_audit["genre_excluded_detail"]:
        lines.append("\n### Artists removed by genre filter\n")
        import pandas as pd
        detail_df = pd.DataFrame(genre_audit["genre_excluded_detail"]).set_index("artist")
        lines.append(detail_df.to_markdown())
        lines.append("\n")
else:
    lines.append(
        "\n**Genre filter:** not applied — `data/track_meta.json` not found. Run "
        "`python3 src/enrich.py` (needs internet) then re-run this script to add "
        "the genre-based filter layer and the genre sections below.\n"
    )

lines.append("## Listening by year\n")
lines.append(stats["by_year"].to_markdown())
lines.append("\n## Top artists (lifetime)\n")
lines.append(stats["top_artists_lifetime"].to_markdown())
lines.append("\n## Top tracks (lifetime)\n")
lines.append(stats["top_tracks_lifetime"].to_markdown())
lines.append("\n## Top artist each year\n")
lines.append(stats["top_artist_per_year"].to_markdown())
lines.append("\n## Highest skip rate (min 50 plays)\n")
lines.append(stats["most_skipped"].to_markdown())
lines.append("\n## Discovery rate (% of plays that were new-to-you tracks)\n")
lines.append(stats["discovery_rate"].to_markdown())

lines.append("\n## Christmas corner\n")
lines.append(christmas.groupby("Track Description")["Play Count"].sum().sort_values(ascending=False).head(10).to_markdown())

if meta:
    gstats = genre_stats(clean, cfg["report"]["top_n"])
    lines.append("\n## Top genres (lifetime)\n")
    lines.append(gstats["top_genres_lifetime"].to_markdown())
    lines.append("\n## Top genre each year\n")
    lines.append(gstats["top_genre_per_year"].to_markdown())
    lines.append("\n## Genre evolution by year (play counts)\n")
    lines.append(gstats["genre_by_year"].to_markdown())
else:
    lines.append(
        "\n## Genre dimension — pending\n\n"
        "Run `python3 src/enrich.py` to populate `data/track_meta.json`, then "
        "re-run this script.\n"
    )

out = Path(__file__).parent / "output" / "wrapped_report.md"
out.write_text("\n".join(lines))
print(f"Wrote {out}")
print("\n".join(lines[:6]))
