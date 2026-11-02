#!/usr/bin/env python3
"""Hour-by-hour *song replacement* for existing Xiaozhi JioSaavn DJ JSON.

Keeps the existing six JSON filenames and song schema. Uses the existing
metadata-filtering builder; does not access or modify ESP32 firmware.

A new track means not present in the *previous published playlist*.
We prefer tracks also absent from the last six published playlists.
New music is contingent on provider availability and catalog breadth:
never falsely claim new songs when an API fails or the pool is exhausted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import tempfile
import time
from typing import Any

MODES = {
    "artist_nonstop": "Kumar Sanu",
    "hindi_90s": "",
    "romantic": "",
    "sad": "",
    "ghazal": "",
    "bangla_classic": "",
}
HISTORY_VERSION = 1
HISTORY_WINDOW = 6
REQUIRED_SONG_KEYS = ("title", "artist", "audio_url")


def key(song: dict[str, Any]) -> str:
    """Identity from published track metadata; avoids duplicate reissues by ID alone."""
    import re
    import unicodedata

    def clean(value: Any) -> str:
        s = unicodedata.normalize("NFKC", str(value or "")).casefold()
        return re.sub(r"\s+", " ", re.sub(r"[^\w\u0980-\u09ff]+", " ", s)).strip()

    # One song can have several different IDs across JioSaavn entries.
    # Compare title + searched artist to avoid replaying the same title as 'new'.
    return clean(song.get("title")) + "|" + clean(song.get("artist"))


def valid_song(song: Any) -> bool:
    return (isinstance(song, dict)
            and all(isinstance(song.get(k), str) and song[k].strip() for k in REQUIRED_SONG_KEYS)
            and song["audio_url"].startswith("https://"))


def unique_songs(songs: Any) -> list[dict[str, Any]]:
    if not isinstance(songs, list):
        return []
    seen_keys: set[str] = set()
    seen_ids: set[str] = set()
    result = []
    for song in songs:
        if not valid_song(song):
            continue
        k = key(song)
        sid = str(song.get("id") or "")
        if not k or k in seen_keys or (sid and sid in seen_ids):
            continue
        seen_keys.add(k)
        if sid:
            seen_ids.add(sid)
        result.append(song)
    return result


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, UnicodeError, json.JSONDecodeError) as ex:
        raise ValueError(f"Cannot safely read {path}: {ex}") from ex


def provider_urls(config_path: Path) -> list[str]:
    cfg = read_json(config_path, {})
    if not isinstance(cfg, dict) or not isinstance(cfg.get("providers"), list):
        raise ValueError("Missing or invalid music_config.json providers")
    ordered = sorted((p for p in cfg["providers"] if isinstance(p, dict)),
                     key=lambda p: p.get("priority", 99))
    providers = [str(p.get("base_url", "")).rstrip("/") for p in ordered
                 if isinstance(p, dict) and p.get("enabled") and
                 str(p.get("base_url", "")).startswith("https://")]
    if not providers:
        raise ValueError("No enabled HTTPS JioSaavn providers")
    return providers


def build_candidates(mode: str, artist: str, providers: list[str],
                     candidate_limit: int, per_query: int) -> dict[str, Any]:
    from dj_six_modes import build  # Existing validated artist / mood / year filters.
    return build(mode, artist, providers, limit=candidate_limit, per_query=per_query)


def choose_songs(candidates: list[dict[str, Any]],
                 previous: list[dict[str, Any]],
                 past_snapshots: list[list[str]],
                 count: int, hour: int, mode: str) -> tuple[list[dict[str, Any]], int]:
    """Prefer NEW candidates; fill from old valid songs if the catalog is thin."""
    current = unique_songs(candidates)
    old = unique_songs(previous)
    previous_keys = {key(x) for x in old}
    recent_keys = {s for snap in past_snapshots for s in snap if isinstance(s, str)}
    rng = random.Random(f"dj-hourly-v1:{hour}:{mode}")
    new_never_recent = [s for s in current if key(s) not in previous_keys and key(s) not in recent_keys]
    new_but_recent = [s for s in current if key(s) not in previous_keys and key(s) in recent_keys]
    old_candidates = [s for s in current if key(s) in previous_keys]
    rng.shuffle(new_never_recent)
    rng.shuffle(new_but_recent)
    rng.shuffle(old_candidates)
    rng.shuffle(old)
    ordered = new_never_recent + new_but_recent + old_candidates + old
    chosen = unique_songs(ordered)[:count]
    novelty = len([s for s in chosen if key(s) not in previous_keys])
    return chosen, novelty


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                         dir=path.parent, delete=False) as f:
            temp_path = Path(f.name)
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def refresh_all(config_path: Path, output_dir: Path, history_path: Path,
                *, hour: int | None = None, candidate_limit: int = 150,
                per_query: int = 70, min_new: int = 1) -> dict[str, dict[str, Any]]:
    if hour is None:
        hour = int(time.time() // 3600)
    if not 1 <= candidate_limit <= 200 or not 1 <= per_query <= 100 or min_new < 1:
        raise ValueError("Invalid refresh limits")
    providers = provider_urls(config_path)
    history = read_json(history_path, {"version": HISTORY_VERSION, "modes": {}})
    if not isinstance(history, dict) or history.get("version") != HISTORY_VERSION or not isinstance(history.get("modes"), dict):
        raise ValueError("Invalid DJ history format; refusing to overwrite")

    pending: dict[Path, dict[str, Any]] = {}
    statuses: dict[str, dict[str, Any]] = {}
    history_changed = False
    for mode, artist in MODES.items():
        path = output_dir / f"{mode}.json"
        previous = read_json(path, {})
        if not isinstance(previous, dict) or (previous and previous.get("mode") != mode):
            raise ValueError(f"Invalid previous JSON mode: {path}")
        previous_songs = unique_songs(previous.get("songs", []))
        raw_history = history["modes"].get(mode, {})
        entry = raw_history if isinstance(raw_history, dict) else {}
        if entry.get("last_hour") == hour:
            statuses[mode] = {"status": "already_published_this_hour", "new_songs": 0, "total": len(previous_songs)}
            continue
        snapshots = entry.get("recent", [])
        if not isinstance(snapshots, list):
            snapshots = []
        count = 30  # Preserve the published fixed 30-track contract, even if older JSON has duplicate titles.
        try:
            built = build_candidates(mode, artist, providers, candidate_limit, per_query)
            if not isinstance(built, dict):
                raise ValueError("candidate builder returned non-object")
            candidates = unique_songs(built.get("songs", []))
        except Exception as ex:
            # Provider outage must never clobber the last working playlist.
            statuses[mode] = {"status": "source_unavailable", "new_songs": 0,
                              "total": len(previous_songs), "error": type(ex).__name__}
            continue
        if len(candidates) < count:
            statuses[mode] = {"status": "insufficient_valid_candidates", "new_songs": 0,
                              "total": len(previous_songs), "candidates": len(candidates)}
            continue
        chosen, novelty = choose_songs(candidates, previous_songs, snapshots, count, hour, mode)
        if len(chosen) != count or (previous_songs and novelty < min_new):
            statuses[mode] = {"status": "no_new_songs" if novelty < min_new else "too_few_songs",
                              "new_songs": 0, "total": len(previous_songs), "candidates": len(candidates)}
            continue
        if [key(s) for s in chosen] == [key(s) for s in previous_songs]:
            statuses[mode] = {"status": "unchanged", "new_songs": 0, "total": count}
            continue

        # Preserve the exact legacy keys for device compatibility; do not edit providers.
        result = dict(previous) if previous else dict(built)
        result["songs"] = chosen
        result["playlist_count"] = count
        result["audit"] = built.get("audit", {})
        result["fetch_errors"] = built.get("fetch_errors", {})
        # Retain original preview_only flag and all per-song metadata, without
        # inventing playback validation or claiming audio URL success.
        if any(not valid_song(s) for s in result["songs"]):
            raise ValueError(f"Invalid song generated for {mode}")
        pending[path] = result
        current_snapshot = [key(s) for s in chosen]
        recent = [current_snapshot] + [x for x in snapshots if isinstance(x, list)]
        history["modes"][mode] = {"last_hour": hour, "recent": recent[:HISTORY_WINDOW]}
        history_changed = True
        statuses[mode] = {"status": "updated", "new_songs": novelty,
                          "total": count, "candidates": len(candidates),
                          "first": chosen[0]["title"]}

    # Stage and validate ALL modes before any file replacement.
    for path, obj in pending.items():
        if not isinstance(obj.get("songs"), list) or obj.get("playlist_count") != len(obj["songs"]):
            raise ValueError(f"Invalid output: {path}")
        if len(unique_songs(obj["songs"])) != len(obj["songs"]):
            raise ValueError(f"Duplicate/invalid song in output: {path}")
    for path, obj in pending.items():
        atomic_json(path, obj)
    if history_changed:
        atomic_json(history_path, history)
    return statuses


def main() -> None:
    p = argparse.ArgumentParser(description="Hourly novelty-first DJ JSON publisher")
    p.add_argument("--config", type=Path, default=Path("music_config.json"))
    p.add_argument("--output-dir", type=Path, default=Path("data/dj"))
    p.add_argument("--history", type=Path, default=Path("data/dj/.hourly_history.json"))
    p.add_argument("--candidate-limit", type=int, default=150)
    p.add_argument("--per-query", type=int, default=70)
    p.add_argument("--min-new", type=int, default=1)
    p.add_argument("--hour", type=int, default=None, help="UTC hour for deterministic offline test")
    args = p.parse_args()
    status = refresh_all(args.config, args.output_dir, args.history,
                         hour=args.hour, candidate_limit=args.candidate_limit,
                         per_query=args.per_query, min_new=args.min_new)
    for mode, details in status.items():
        print(f"{mode}: {json.dumps(details, ensure_ascii=False)}", flush=True)
    if not any(x.get("status") in ("updated", "already_published_this_hour", "no_new_songs", "unchanged")
               for x in status.values()):
        raise SystemExit("No healthy DJ mode: provider failures or insufficient candidates")


if __name__ == "__main__":
    main()
