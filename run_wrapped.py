"""Run the full Wrapped analysis and write output/wrapped_report.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from pipeline import apply_filters, load_config, load_history, wrapped_stats

cfg = load_config()
df = load_history(cfg)
clean, audit, christmas = apply_filters(df, cfg)
stats = wrapped_stats(clean, cfg["report"]["top_n"])

lines = ["# Lifetime Wrapped — filtered\n"]
lines.append(f"**Filter audit:** removed {audit['sleep_plays_removed']:,} sleep plays "
             f"({audit['sleep_artists']} artists), {audit['focus_plays_removed']:,} focus-music plays ({len(audit['focus_artists'])} artists) and {audit['blocked_plays_removed']:,} blocked-artist plays. "
             f"Remaining: {audit['plays_remaining']:,} plays, ~{audit['hours_remaining']:,} hours. "
             f"Christmas plays held separately: {audit['christmas_plays']:,}.\n")

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

out = Path(__file__).parent / "output" / "wrapped_report.md"
out.write_text("\n".join(lines))
print(f"Wrote {out}")
print("\n".join(lines[:6]))
