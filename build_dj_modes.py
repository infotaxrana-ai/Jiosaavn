#!/usr/bin/env python3
"""Xiaozhi DJ Step 3 v2: metadata-verified playlist PREVIEW only.

No publishing, device calls, streaming or firmware modification.
Track-level explicit metadata is required for dated/genre-constrained modes.
"""
import argparse
import datetime as dt
import json
import re
import urllib.parse
import urllib.request
from collections import Counter, deque
from pathlib import Path
from build_dj import filter_songs, get_results, norm

MODES = {
    "artist_nonstop": ["Kumar Sanu"],
    "hindi_90s_mix": ["Kumar Sanu", "Udit Narayan", "Alka Yagnik", "Anuradha Paudwal", "Abhijeet Bhattacharya"],
    "hindi_classic_movie_1970_2010": [
        "Kishore Kumar", "Mohammed Rafi", "Mukesh", "Lata Mangeshkar",
        "Asha Bhosle", "Manna Dey", "Kumar Sanu", "Udit Narayan",
        "Alka Yagnik", "Anuradha Paudwal", "Kavita Krishnamurthy",
        "Sonu Nigam", "Abhijeet Bhattacharya", "Shreya Ghoshal"
    ],
    "bangla_classic_mix": ["Runa Laila", "Sabina Yasmin", "Kanak Chapa", "Andrew Kishore", "Subir Nandi"],
    "ghazal_mix": ["Pankaj Udhas", "Jagjit Singh", "Ghulam Ali"],
}
CONSTRAINTS = {
    "hindi_90s_mix": (1990, 1999, False),
    "hindi_classic_movie_1970_2010": (1970, 2010, True),
    "ghazal_mix": (None, None, False),
}
GHZ = re.compile(r"\bghazals?\b|গ[জয]ল|غزل", re.I)
FILM = re.compile(r"\b(?:bollywood|hindi film|film soundtrack|movie soundtrack|motion picture soundtrack|film music)\b", re.I)
NONFILM = re.compile(r"\b(?:non[- ]?film|independent|private album)\b", re.I)


def key(text):
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def extract_year(song):
    """Return a year only from explicit release metadata; never infer from singer."""
    fields = [song.get(k) for k in ("year", "releaseYear", "release_year", "releaseDate", "release_date", "date")]
    album = song.get("album")
    if isinstance(album, dict):
        fields += [album.get(k) for k in ("year", "releaseYear", "release_year", "releaseDate", "release_date")]
    years = []
    for value in fields:
        if isinstance(value, int) and not isinstance(value, bool):
            year = value
        elif isinstance(value, str):
            match = re.match(r"^\s*((?:19|20)\d{2})(?:\D|$)", value)
            if not match:
                continue
            year = int(match.group(1))
        else:
            continue
        if 1900 <= year <= dt.datetime.now(dt.timezone.utc).year + 1:
            years.append(year)
    if not years or len(set(years)) != 1:
        return None
    return years[0]


def flatten_labels(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [z for x in value for z in flatten_labels(x)]
    if isinstance(value, dict):
        return [z for k in ("name", "title", "type", "genre") for z in flatten_labels(value.get(k))]
    return []


def labels(song, keys):
    return " | ".join(z for k in keys for z in flatten_labels(song.get(k)))


def is_ghazal(song):
    # Artist alone never proves genre. Require genre/tag or explicit title/album genre label.
    genre = labels(song, ("genre", "genres", "tags", "category", "categories", "type"))
    title = labels(song, ("name", "title"))
    album = song.get("album")
    album_title = labels(album, ("name", "title", "genre", "genres")) if isinstance(album, dict) else str(album or "")
    return bool(GHZ.search(" | ".join((genre, title, album_title))))


def is_hindi_movie(song):
    # Require positive film/movie evidence, rather than assuming old singer = film song.
    # A clearly explicit movie name is acceptable only via movie/film metadata field.
    if song.get("isFilmSong") is True or song.get("is_film_song") is True:
        return True
    if song.get("isFilmSong") is False or song.get("is_film_song") is False:
        return False
    movie = song.get("movie") or song.get("film") or song.get("movieName") or song.get("filmName")
    if isinstance(movie, str) and movie.strip():
        return True
    context = labels(song, ("genre", "genres", "tags", "category", "categories", "type"))
    if NONFILM.search(context):
        return False
    return bool(FILM.search(context))


def fetch_search(query, providers, limit):
    failures = []
    for base in providers:
        p = urllib.parse.urlparse(base)
        if p.scheme != "https" or not p.hostname:
            continue
        url = base.rstrip("/") + "/api/search/songs?" + urllib.parse.urlencode({"query": query, "limit": limit})
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "XiaozhiDJStep3Review/2.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as response:
                if urllib.parse.urlparse(response.geturl()).scheme != "https":
                    raise ValueError("unsafe redirect")
                b = response.read(2_500_001)
                if len(b) > 2_500_000:
                    raise ValueError("large response")
                payload = json.loads(b.decode("utf-8"))
                if not isinstance(payload, (dict, list)) or not get_results(payload):
                    failures.append("empty search results")
                    continue
                return payload
        except (OSError, ValueError, json.JSONDecodeError) as e:
            failures.append(type(e).__name__)
    raise RuntimeError("Providers unavailable: " + ", ".join(failures))


def candidates(payload, artist, mode, max_per_artist):
    filtered = filter_songs(payload, artist, max_items=max_per_artist)
    original = get_results(payload)
    by_id = {str(x.get("id")): x for x in original if isinstance(x, dict) and x.get("id") is not None}
    # Title-based fallback only when IDs are absent and artist filter already accepted.
    by_title = {}
    for row in original:
        if isinstance(row, dict):
            by_title.setdefault(norm(row.get("name") or row.get("title")), []).append(row)
    counts = Counter(filtered["counts"])
    accepted = []
    year_min, year_max, must_movie = CONSTRAINTS.get(mode, (None, None, False))
    for song in filtered["songs"]:
        metadata = by_id.get(str(song["id"])) if song.get("id") is not None else None
        if metadata is None:
            alternatives = by_title.get(norm(song["title"]), [])
            if len(alternatives) == 1:
                metadata = alternatives[0]
        if metadata is None:
            counts["unverifiable_metadata"] += 1
            continue
        year = extract_year(metadata)
        if year_min is not None:
            if year is None:
                counts["missing_year"] += 1
                continue
            if year < year_min or year > year_max:
                counts["outside_year_range"] += 1
                continue
        if mode == "ghazal_mix" and not is_ghazal(metadata):
            counts["genre_unverified"] += 1
            continue
        if must_movie and not is_hindi_movie(metadata):
            counts["film_unverified"] += 1
            continue
        # JioSaavn search language metadata is inconsistent. Never claim language verified.
        song["verified_year"] = year
        song["genre_evidence"] = "ghazal metadata/title" if mode == "ghazal_mix" else None
        song["film_evidence"] = "explicit film metadata" if must_movie else None
        accepted.append(song)
    counts["selected"] = len(accepted)
    return accepted, dict(counts)


def build(mode, fixture_dir="dj_fixtures", max_songs=30, live=False, providers=None):
    if mode not in MODES:
        raise ValueError("Unknown DJ mode")
    if not 1 <= max_songs <= 120:
        raise ValueError("limit must be 1..120")
    queues, audits, missing = [], {}, []
    for artist in MODES[mode]:
        file = Path(fixture_dir) / (key(artist) + ".json")
        if live:
            try:
                payload = fetch_search(artist, providers or [], max(40, max_songs))
            except RuntimeError:
                missing.append(artist + " (API unavailable)")
                continue
        elif file.is_file():
            payload = json.loads(file.read_text(encoding="utf-8"))
        else:
            missing.append(artist + " (fixture missing)")
            continue
        songs, audit = candidates(payload, artist, mode, max_per_artist=max(40, max_songs))
        audits[artist] = audit
        queues.append(deque(songs))
    output, seen_ids, seen_urls, seen_titles = [], set(), set(), set()
    while len(output) < max_songs and any(queues):
        for q in queues:
            if not q:
                continue
            song = q.popleft()
            sid = str(song.get("id") or "")
            title_key = (norm(song["title"]), norm(song["artist"]))
            if (sid and sid in seen_ids) or song["audio_url"] in seen_urls or title_key in seen_titles:
                continue
            if sid:
                seen_ids.add(sid)
            seen_urls.add(song["audio_url"])
            seen_titles.add(title_key)
            output.append(song)
            if len(output) >= max_songs:
                break
    return {
        "schema_version": 2, "preview_only": True, "mode": mode,
        "constraints": {"year_range": [1990, 1999] if mode == "hindi_90s_mix" else [1970, 2010] if mode == "hindi_classic_movie_1970_2010" else None,
                        "ghazal_evidence_required": mode == "ghazal_mix", "film_evidence_required": mode == "hindi_classic_movie_1970_2010"},
        "playlist_count": len(output), "songs": output,
        "source_audits": audits, "unavailable_artists": missing,
        "limitations": ["Incomplete year/genre/film metadata causes safe rejection; this cannot guarantee all songs from 1970-2010.",
                        "Audio URLs are metadata only; not verified playable with ESP32.",
                        "No ESP32/MCP/Radio Queue integration; no changes to music_config.json or published playlists."]
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=MODES, required=True)
    p.add_argument("--fixtures", default="dj_fixtures")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--live", action="store_true")
    p.add_argument("--config", default="music_config.json")
    p.add_argument("--output", default="dj_mode_preview.json")
    args = p.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.live else {}
    providers = [x["base_url"] for x in sorted(config.get("providers", []), key=lambda x: x.get("priority", 99)) if x.get("enabled") and x.get("base_url")]
    result = build(args.mode, args.fixtures, args.limit, args.live, providers)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DJ STEP 3 V2", args.mode, "accepted", result["playlist_count"])
    print("Per-source filter audits:", json.dumps(result["source_audits"], ensure_ascii=False))
    print("PREVIEW ONLY: firmware and playback untouched")


if __name__ == "__main__":
    main()
