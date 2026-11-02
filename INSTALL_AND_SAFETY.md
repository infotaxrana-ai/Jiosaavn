# Hourly NEW-Song DJ Playlist Sync — Safe Patch

Repository: `https://github.com/infotaxrana-ai/Jiosaavn`

## Purpose

- Every hour (GitHub Actions `23 * * * *`, UTC), fetch JioSaavn search candidates again for all six existing modes.
- Use the existing `dj_six_modes.build()` artist / mood / genre filters, without changing its source.
- Consider up to 150 candidates per playlist; select 30 songs, prioritizing songs **not in the previous JSON** and preferably not in the last six published playlists.
- Publish only if there is at least one *actual* different song in that mode. Reordering the same 30 tracks alone is not counted as fresh.
- If API is down, returns too few tracks, or no novel tracks exist, keep the last published JSON unmodified.
- Keep `schema_version`, `mode`, `playlist_count`, `preview_only`, `songs` and existing song metadata compatible with the original consumer.
- Preserve original firmware, backups, original `dj_six_modes.py`, `music_config.json` and all other project files.

## Add or replace exactly these three repository files

1. **ADD** `hourly_dj_refresh.py` at repository root.
2. **ADD** `test_hourly_dj_refresh.py` at repository root.
3. **REPLACE** `.github/workflows/dj-publish-playlists.yml` with the full supplied workflow.

Do **not** delete or alter the current six `data/dj/*.json`, `dj_six_modes.py`, or any proven firmware files manually.

The automated job will create `data/dj/.hourly_history.json` to remember the previous six accepted playlists; it is not a user-editable source of truth.

## Validation before relying on updates

In GitHub → Actions → **Publish Xiaozhi DJ Playlists** → **Run workflow**, ensure:

- Regression tests pass (includes existing tests plus `test_hourly_dj_refresh.py`).
- New track counts are logged per mode. "NO NEW TRACKS" means existing JSON was intentionally preserved.
- The job pushes only `data/dj/` JSON changes (not firmware changes).
- The first track in a changed JSON differs when new candidates exist.

GitHub scheduled workflow time is **best effort**; individual runs can be delayed or skipped. New songs are also dependent on the JioSaavn API catalog and availability.

**Playback limitation:** Publishing GitHub JSON does not, by itself, prove the ESP32 will refetch it or interrupt a playing song. That requires a separate later read-only firmware inspection and runtime test.

## Local verification performed

`python -m unittest -v test_hourly_dj_refresh.py` — **10 tests PASS** with simulated JioSaavn metadata.
`python -m compileall -q .` — **PASS**.
`PyYAML safe_load()` of workflow — syntax **PASS** (`on` interpreted as boolean under YAML 1.1 only; GitHub Actions uses workflow syntax with `on:`).

Live API / GitHub workflow execution: **NOT VERIFIED**. The connected GitHub app rejected write requests with HTTP 403 "Resource not accessible by integration", so no live repository modifications occurred.
