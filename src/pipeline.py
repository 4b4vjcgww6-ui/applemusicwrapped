import json
import re
"""Music Wrapped pipeline: load, filter, and analyse Apple Music play history.

Input: Apple Music - Play History Daily Tracks.csv (new-format privacy export).
Each row is one track on one day, with play/skip counts and UTC hour buckets.
"""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
TRACK_META_PATH = ROOT / "data" / "track_meta.json"


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def load_history(cfg: dict) -> pd.DataFrame:
    path = ROOT / "data" / "Apple_Music_-_Play_History_Daily_Tracks.csv"
    df = pd.read_csv(path, low_memory=False)
    df["date"] = pd.to_datetime(df["Date Played"], format="%Y%m%d")
    df["year"] = df["date"].dt.year
    # Track Description is "Artist - Title"; artist = text before first " - "
    df["artist"] = df["Track Description"].str.split(" - ", n=1).str[0].str.strip()
    df["title"] = df["Track Description"].str.split(" - ", n=1).str[1]
    # Hours is a comma-separated list of UTC hour buckets; first bucket is enough
    # for behavioural profiling. Convert to local time.
    tz = cfg["timezone_offset_hours"]
    df["hour_local"] = (
        df["Hours"].astype(str).str.split(",").str[0].astype(float) + tz
    ) % 24
    df["is_homepod"] = df["Source Type"].fillna("").str.contains("HOMEPOD")
    return df


def detect_sleep_artists(df: pd.DataFrame, cfg: dict) -> set[str]:
    sf = cfg["sleep_filter"]
    if not sf["enabled"]:
        return set()
    night = (df["hour_local"] >= sf["night_start"]) | (df["hour_local"] <= sf["night_end"])
    prof = df.assign(night=night).groupby("artist").agg(
        plays=("Play Count", "sum"),
        night_share=("night", "mean"),
        homepod_share=("is_homepod", "mean"),
    )
    behavioural = prof[
        (prof.plays >= sf["min_plays"])
        & (prof.night_share >= sf["night_share"])
        & (prof.homepod_share >= sf["homepod_share"])
    ].index
    kw = "|".join(sf["keywords"])
    keyword_hits = prof.index[prof.index.str.contains(kw, case=False, na=False, regex=True)]
    return set(behavioural) | set(keyword_hits)


def detect_focus_artists(df: pd.DataFrame, cfg: dict, already_excluded: set[str]) -> set[str]:
    """Daytime focus/ambient acts: heavy repeats of few tracks, never skipped."""
    ff = cfg["focus_filter"]
    if not ff["enabled"]:
        return set()
    pool = df[~df["artist"].isin(already_excluded)]
    p = pool.groupby("artist").agg(
        plays=("Play Count", "sum"),
        skips=("Skip Count", "sum"),
        tracks=("Track Identifier", "nunique"),
    )
    hits = p[
        (p.plays >= ff["min_plays"])
        & (p.skips / p.plays <= ff["max_skip_rate"])
        & (p.plays / p.tracks >= ff["min_plays_per_track"])
    ]
    return set(hits.index)


def tag_christmas(df: pd.DataFrame, cfg: dict) -> pd.Series:
    cf = cfg["christmas_filter"]
    kw = "|".join(re.escape(k) for k in cf["keywords"])
    by_kw = df["title"].fillna("").str.contains(kw, case=False, regex=True)
    nd = df.date.dt.month.isin([11, 12])
    seasonal = df.assign(nd=nd, nd_year=df.year.where(nd)).groupby("Track Identifier").agg(
        plays=("Play Count", "sum"),
        nd_share=("nd", "mean"),
        nd_years=("nd_year", "nunique"),
    )
    seasonal_ids = set(seasonal[
        (seasonal.nd_share >= cf["seasonal_share"])
        & (seasonal.plays >= cf["min_plays"])
        & (seasonal.nd_years >= 2)  # recurs across Decembers — not a Nov/Dec release binge
    ].index)
    return by_kw | df["Track Identifier"].isin(seasonal_ids)


def apply_filters(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    sleep_artists = detect_sleep_artists(df, cfg)
    blocked = set(cfg["blocked_artists"])
    focus_artists = detect_focus_artists(df, cfg, sleep_artists | blocked)
    mask_sleep = df["artist"].isin(sleep_artists)
    mask_blocked = df["artist"].isin(blocked)
    mask_focus = df["artist"].isin(focus_artists)
    clean = df[~mask_sleep & ~mask_blocked & ~mask_focus].copy()
    clean["is_christmas"] = tag_christmas(clean, cfg)
    mode = cfg["christmas_filter"]["mode"]
    christmas = clean[clean["is_christmas"]].copy()
    if mode in ("exclude", "separate"):
        clean = clean[~clean["is_christmas"]].copy()
    audit = {
        "sleep_artists": len(sleep_artists),
        "sleep_artists_list": sorted(sleep_artists),
        "sleep_plays_removed": int(df.loc[mask_sleep, "Play Count"].sum()),
        "focus_artists": sorted(focus_artists),
        "focus_plays_removed": int(df.loc[mask_focus, "Play Count"].sum()),
        "blocked_plays_removed": int(df.loc[mask_blocked, "Play Count"].sum()),
        "christmas_plays": int(christmas["Play Count"].sum()),
        "plays_remaining": int(clean["Play Count"].sum()),
        "hours_remaining": round(clean["Play Duration Milliseconds"].sum() / 3.6e6),
    }
    return clean, audit, christmas


def load_track_meta() -> dict:
    """Cached iTunes Lookup metadata from src/enrich.py, keyed by str(Track Identifier).
    Returns {} if enrich.py hasn't been run yet — callers should treat that as
    "genre dimension not available" rather than an error."""
    if TRACK_META_PATH.exists():
        return json.loads(TRACK_META_PATH.read_text())
    return {}


def attach_genre(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    df = df.copy()
    tid = df["Track Identifier"].astype("Int64").astype(str)
    df["genre"] = tid.map(lambda i: (meta.get(i) or {}).get("genre"))
    return df


def apply_genre_layer(
    clean: pd.DataFrame, christmas: pd.DataFrame, cfg: dict, meta: dict
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Additional filter layer, run only once data/track_meta.json exists.
    Two jobs, per README: (1) excluded_genres catches ambient/sleep/etc.
    residual the behavioural filters missed; (2) a Christmas-genre tag is
    authoritative for Christmas tagging, catching stray tracks the
    keyword/seasonal heuristic in tag_christmas() missed. Never touches
    `clean`/`christmas` when meta is empty, so the pre-enrichment validated
    checkpoint numbers are reproduced exactly until enrichment actually runs.

    iTunes' actual genre string is "Christmas" (plus subtypes like
    "Christmas: Pop", "Christmas: Jazz", "Christmas: Country",
    "Christmas: Children's", "Christmas: Classic") rather than "Holiday" as
    the README assumed - matched with startswith() to catch all subtypes
    without also matching unrelated genres like "Classic Christian".
    """
    if not meta:
        return clean, christmas, {}

    tagged = attach_genre(clean, meta)

    holiday_mask = tagged["genre"].str.startswith("Christmas", na=False)
    reclassified = tagged[holiday_mask].copy()
    tagged = tagged[~holiday_mask]
    if len(reclassified):
        reclassified["is_christmas"] = True
        christmas = pd.concat([christmas, reclassified], ignore_index=True)

    excluded_genres = set(cfg.get("excluded_genres", []))
    excl_mask = tagged["genre"].isin(excluded_genres)
    removed = tagged[excl_mask].copy()
    kept = tagged[~excl_mask].copy()

    by_genre = removed.groupby("genre")["Play Count"].sum().sort_values(ascending=False)
    detail = (
        removed.groupby(["artist", "genre"])["Play Count"].sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"Play Count": "plays"})
    )
    audit = {
        "holiday_reclassified_plays": int(reclassified["Play Count"].sum()) if len(reclassified) else 0,
        "holiday_reclassified_tracks": sorted(reclassified["Track Description"].unique().tolist()) if len(reclassified) else [],
        "genre_excluded_plays": int(removed["Play Count"].sum()),
        "genre_excluded_artist_count": removed["artist"].nunique(),
        "genre_excluded_by_genre": by_genre.to_dict(),
        "genre_excluded_detail": detail.to_dict(orient="records"),
    }
    return kept, christmas, audit


def genre_stats(df: pd.DataFrame, top_n: int = 15) -> dict:
    """Genre dimension for the report: requires df already has a 'genre' column
    (i.e. it went through attach_genre / apply_genre_layer)."""
    tagged = df.dropna(subset=["genre"])
    out = {}
    out["top_genres_lifetime"] = (
        tagged.groupby("genre")["Play Count"].sum().sort_values(ascending=False).head(top_n)
    )
    out["top_genre_per_year"] = (
        tagged.groupby(["year", "genre"])["Play Count"].sum()
        .reset_index()
        .sort_values("Play Count", ascending=False)
        .groupby("year")
        .first()
        .sort_index()
    )
    out["genre_by_year"] = (
        tagged.groupby(["year", "genre"])["Play Count"].sum().unstack(fill_value=0)
    )
    return out


def wrapped_stats(df: pd.DataFrame, top_n: int = 20) -> dict:
    out = {}
    out["by_year"] = df.groupby("year").agg(
        plays=("Play Count", "sum"),
        hours=("Play Duration Milliseconds", lambda s: round(s.sum() / 3.6e6, 1)),
        unique_tracks=("Track Identifier", "nunique"),
        unique_artists=("artist", "nunique"),
    )
    out["top_artists_lifetime"] = (
        df.groupby("artist")["Play Count"].sum().sort_values(ascending=False).head(top_n)
    )
    out["top_tracks_lifetime"] = (
        df.groupby("Track Description")["Play Count"].sum().sort_values(ascending=False).head(top_n)
    )
    out["top_artist_per_year"] = (
        df.groupby(["year", "artist"])["Play Count"].sum()
        .reset_index()
        .sort_values("Play Count", ascending=False)
        .groupby("year")
        .first()
        .sort_index()
    )
    skips = df.groupby("artist").agg(
        plays=("Play Count", "sum"), skips=("Skip Count", "sum")
    )
    skips = skips[skips.plays >= 50]
    out["most_skipped"] = (skips.skips / skips.plays).sort_values(ascending=False).head(10)
    # Discovery rate: share of each year's plays that are first-ever plays of a track
    first_year = df.groupby("Track Identifier")["year"].min().rename("first_year")
    d = df.merge(first_year, on="Track Identifier")
    out["discovery_rate"] = (
        d.assign(new=d.year == d.first_year)
        .groupby("year")
        .apply(lambda g: round((g.loc[g.new, "Play Count"].sum() / g["Play Count"].sum()) * 100, 1), include_groups=False)
    )
    return out
