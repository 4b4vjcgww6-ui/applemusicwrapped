"""Extract a taste profile from filtered listening history.

Clusters artists by sustained-vs-burst listening (core taste vs phases) and
by engagement-weighted intensity. Genre and release-era dimensions join in
automatically once data/track_meta.json exists (see src/enrich.py) — until
then those fields are left null and generated_from.genre_enrichment_available
is false, so this script is safe to run before or after enrichment.

Usage: python3 src/taste.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import apply_filters, attach_genre, load_config, load_history, load_track_meta

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "output" / "taste_profile.json"

CORE_MIN_YEARS = 3          # spread across at least this many calendar years
CORE_MAX_YEAR_SHARE = 0.60  # no single year may hold more than this share of plays
PHASE_MIN_PLAYS = 15        # below this, a short-window artist is noise, not a phase


def attach_era(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """Release decade from enrichment metadata's releaseDate (e.g. '2016-07-01...' -> 2010)."""
    df = df.copy()
    tid = df["Track Identifier"].astype("Int64").astype(str)

    def decade(i):
        entry = meta.get(i) or {}
        rd = entry.get("release_date")
        if not rd:
            return None
        try:
            year = int(str(rd)[:4])
        except ValueError:
            return None
        return (year // 10) * 10

    df["era_decade"] = tid.map(decade)
    return df


def dominant_by_play(df: pd.DataFrame, col: str) -> pd.Series:
    """Most common value of `col` per artist, weighted by Play Count."""
    sub = df.dropna(subset=[col])
    if sub.empty:
        return pd.Series(dtype=object)
    weighted = sub.groupby(["artist", col])["Play Count"].sum().reset_index()
    idx = weighted.groupby("artist")["Play Count"].idxmax()
    return weighted.loc[idx].set_index("artist")[col]


def classify(row) -> str:
    if row.years_active >= CORE_MIN_YEARS and row.max_year_share <= CORE_MAX_YEAR_SHARE:
        return "core"
    if row.plays >= PHASE_MIN_PLAYS:
        return "phase"
    return "minor"


def artist_profile(df: pd.DataFrame) -> pd.DataFrame:
    # Rows with Play Count 0 (Skip Count > 0) are catalogue previews skipped
    # before any real listening — not taste signal, and they'd divide-by-zero
    # below. They stay in the filtered dataset for run_wrapped.py's skip-rate
    # stats; here they're just excluded from the artist grouping.
    df = df[df["Play Count"] > 0]
    g = df.groupby("artist")
    prof = g.agg(
        plays=("Play Count", "sum"),
        skips=("Skip Count", "sum"),
        unique_tracks=("Track Identifier", "nunique"),
        first_play=("date", "min"),
        last_play=("date", "max"),
        years_active=("year", "nunique"),
    )
    prof["completion_rate"] = (1 - prof.skips / prof.plays).clip(lower=0, upper=1).round(3)

    natural = df.assign(natural=df["End Reason Type"].eq("NATURAL_END_OF_TRACK"))
    natural_share = (
        natural.groupby("artist").apply(
            lambda x: (x.loc[x.natural, "Play Count"].sum() / x["Play Count"].sum()),
            include_groups=False,
        ).round(3)
    )
    prof["natural_end_share"] = natural_share

    prof["repeat_rate"] = (prof.plays / prof.unique_tracks).round(2)
    prof["engagement_quality"] = (
        (prof.completion_rate + prof.natural_end_share) / 2
    ).round(3)
    prof["weighted_plays"] = (prof.plays * prof.engagement_quality).round(1)
    prof["span_days"] = (prof.last_play - prof.first_play).dt.days

    # Diagnostic only — near-miss of the focus_filter signature (config.yaml:
    # max_skip_rate 0.03, min_plays_per_track 4) at a looser margin. These are
    # not removed (that's genre enrichment's job per README), just flagged so
    # they aren't mistaken for real taste when writing up profiles.
    prof["likely_ambient_residual"] = (
        (prof.completion_rate >= 0.95) & (prof.repeat_rate >= 4) & (prof.plays >= 15)
    )

    year_plays = df.groupby(["artist", "year"])["Play Count"].sum().reset_index()
    max_year_share = year_plays.groupby("artist").apply(
        lambda g: g["Play Count"].max() / g["Play Count"].sum(), include_groups=False
    )
    prof["max_year_share"] = max_year_share.round(3)

    prof["classification"] = prof.apply(classify, axis=1)

    rank = prof["weighted_plays"].rank(method="first")
    cuts = pd.qcut(rank, q=[0, 0.6, 0.85, 1.0], labels=["low", "medium", "high"])
    prof["intensity_tier"] = cuts

    return prof.sort_values("weighted_plays", ascending=False)


def top_tracks_by_artist(df: pd.DataFrame, artists: list[str], n: int = 3) -> dict[str, list[dict]]:
    pool = df[df["artist"].isin(artists) & (df["Play Count"] > 0)]
    t = pool.groupby(["artist", "title"]).agg(
        plays=("Play Count", "sum"), skips=("Skip Count", "sum")
    ).reset_index()
    t["completion_rate"] = (1 - t.skips / t.plays).clip(lower=0, upper=1).round(3)
    out: dict[str, list[dict]] = {}
    for artist, group in t.groupby("artist"):
        top = group.sort_values("plays", ascending=False).head(n)
        out[artist] = [
            {"title": r.title, "plays": int(r.plays), "completion_rate": r.completion_rate}
            for r in top.itertuples()
        ]
    return out


def prof_to_records(prof: pd.DataFrame, top_tracks: dict) -> list[dict]:
    records = []
    for artist, r in prof.iterrows():
        records.append({
            "artist": artist,
            "plays": int(r.plays),
            "unique_tracks": int(r.unique_tracks),
            "completion_rate": r.completion_rate,
            "natural_end_share": r.natural_end_share,
            "repeat_rate": r.repeat_rate,
            "engagement_quality": r.engagement_quality,
            "weighted_plays": r.weighted_plays,
            "first_play": r.first_play.date().isoformat(),
            "last_play": r.last_play.date().isoformat(),
            "years_active": int(r.years_active),
            "max_year_share": r.max_year_share,
            "classification": r.classification,
            "intensity_tier": str(r.intensity_tier),
            "likely_ambient_residual": bool(r.likely_ambient_residual),
            "genre": r.genre if "genre" in prof.columns and pd.notna(r.genre) else None,
            "era_decade": (
                int(r.era_decade) if "era_decade" in prof.columns and pd.notna(r.era_decade) else None
            ),
            "top_tracks": top_tracks.get(artist, []),
        })
    return records


def main() -> None:
    cfg = load_config()
    raw = load_history(cfg)
    clean, audit, christmas = apply_filters(raw, cfg)

    meta = load_track_meta()
    enriched = bool(meta)
    if enriched:
        clean = attach_genre(clean, meta)
        clean = attach_era(clean, meta)
    else:
        clean = clean.assign(genre=None, era_decade=None)

    prof = artist_profile(clean)
    if enriched:
        prof["genre"] = dominant_by_play(clean, "genre").reindex(prof.index)
        prof["era_decade"] = dominant_by_play(clean, "era_decade").reindex(prof.index)

    top_tracks = top_tracks_by_artist(clean, list(prof.index), n=3)
    records = prof_to_records(prof, top_tracks)

    result = {
        "generated_from": {
            "plays_analysed": int(clean["Play Count"].sum()),
            "artists_analysed": int(prof.shape[0]),
            "genre_enrichment_available": enriched,
            "note": None if enriched else (
                "data/track_meta.json not found — run src/enrich.py first to "
                "populate genre and era_decade fields. All other fields below "
                "(core/phase classification, engagement weighting, intensity "
                "tiers) are genre-independent and complete."
            ),
        },
        "thresholds": {
            "core_min_years": CORE_MIN_YEARS,
            "core_max_year_share": CORE_MAX_YEAR_SHARE,
            "phase_min_plays": PHASE_MIN_PLAYS,
        },
        "counts_by_classification": prof["classification"].value_counts().to_dict(),
        "likely_ambient_residual_count": int(prof["likely_ambient_residual"].sum()),
        "artists": records,
    }

    OUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT_PATH}")
    print(f"{prof.shape[0]} artists analysed: "
          f"{(prof.classification == 'core').sum()} core, "
          f"{(prof.classification == 'phase').sum()} phase, "
          f"{(prof.classification == 'minor').sum()} minor.")
    print(f"Genre enrichment available: {enriched}")


if __name__ == "__main__":
    main()
