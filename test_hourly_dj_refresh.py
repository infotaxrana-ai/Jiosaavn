import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from hourly_dj_refresh import (
    MODES, choose_songs, key, read_json, refresh_all, unique_songs,
)


def song(i, artist="Kumar Sanu"):
    return {"id": f"id-{i}", "title": f"Song {i}", "artist": artist,
            "actual_artists": [artist], "audio_url": f"https://example.com/{i}_48.mp4"}


class HourlyDJTests(unittest.TestCase):
    def test_selection_uses_actual_new_songs_not_merely_rotation(self):
        old = [song(i) for i in range(30)]
        pool = [song(i) for i in range(80)]
        picked, n = choose_songs(pool, old, [], 30, 500, "hindi_90s")
        self.assertEqual(len(picked), 30)
        self.assertEqual(n, 30)
        self.assertTrue(all(key(s) not in {key(x) for x in old} for s in picked))

    def test_title_duplicate_with_different_ids_is_not_new(self):
        duplicated = song(1)
        duplicated["id"] = "other-id"
        unique = unique_songs([song(1), duplicated, song(2)])
        self.assertEqual(len(unique), 2)

    def test_recent_history_preferred(self):
        old = [song(0), song(1)]
        picked, n = choose_songs([song(2), song(3), song(4), song(5)], old,
                                 [[key(song(2)), key(song(3))]], 2, 500, "sad")
        self.assertEqual({key(s) for s in picked}, {key(song(4)), key(song(5))})
        self.assertEqual(n, 2)

    def setup_env(self, root):
        d = Path(root) / "data/dj"
        d.mkdir(parents=True)
        conf = Path(root) / "music_config.json"
        conf.write_text(json.dumps({"providers": [{"enabled": True, "priority": 1,
                         "base_url": "https://example.org"}]}))
        for mode in MODES:
            (d / f"{mode}.json").write_text(json.dumps({
                "schema_version": 1, "preview_only": True, "mode": mode,
                "playlist_count": 30, "songs": [song(i) for i in range(30)],
                "audit": {}, "fetch_errors": {}, "limitations": []
            }))
        return conf, d, d / ".hourly_history.json"

    def test_end_to_end_six_modes_atomic_schema_and_idempotence(self):
        with tempfile.TemporaryDirectory() as root:
            c, d, h = self.setup_env(root)
            def builder(mode, artist, providers, limit, per_query):
                return {"songs": [song(i) for i in range(80)]}
            with patch("hourly_dj_refresh.build_candidates", side_effect=builder) as mock:
                result = refresh_all(c, d, h, hour=12345)
                self.assertEqual(mock.call_count, 6)
                self.assertTrue(all(v["new_songs"] == 30 for v in result.values()))
                self.assertEqual(len(read_json(h, {})["modes"]), 6)
                for mode in MODES:
                    updated = read_json(d/f"{mode}.json", {})
                    self.assertEqual(updated["mode"], mode)
                    self.assertEqual(updated["playlist_count"], 30)
                    self.assertEqual(len(updated["songs"]), 30)
                    self.assertTrue(updated["preview_only"])
                    self.assertNotIn("rotation_hour", updated)
                same = refresh_all(c, d, h, hour=12345)
                self.assertTrue(all(v["status"] == "already_published_this_hour"
                                    for v in same.values()))
                self.assertEqual(mock.call_count, 6)

    def test_original_duplicate_song_title_does_not_reduce_count(self):
        with tempfile.TemporaryDirectory() as root:
            c, d, h = self.setup_env(root)
            p = d / "artist_nonstop.json"
            original = read_json(p, {})
            original["songs"][1] = dict(original["songs"][0], id="duplicate-track-id")
            p.write_text(json.dumps(original))
            with patch("hourly_dj_refresh.build_candidates", return_value={"songs": [song(i) for i in range(80)]}):
                result = refresh_all(c, d, h, hour=12346)
            self.assertEqual(result["artist_nonstop"]["status"], "updated")
            self.assertEqual(read_json(p, {})["playlist_count"], 30)
            self.assertEqual(len(read_json(p, {})["songs"]), 30)

    def test_api_failure_never_overwrites_published_json(self):
        with tempfile.TemporaryDirectory() as root:
            c, d, h = self.setup_env(root)
            before = {m: (d/f"{m}.json").read_bytes() for m in MODES}
            with patch("hourly_dj_refresh.build_candidates", side_effect=RuntimeError("API 429")):
                result = refresh_all(c, d, h, hour=12345)
            self.assertTrue(all(v["status"] == "source_unavailable" for v in result.values()))
            self.assertEqual(before, {m: (d/f"{m}.json").read_bytes() for m in MODES})
            self.assertFalse(h.exists())

    def test_no_new_songs_never_rewrites_playlist(self):
        with tempfile.TemporaryDirectory() as root:
            c, d, h = self.setup_env(root)
            before = {m: (d/f"{m}.json").read_bytes() for m in MODES}
            with patch("hourly_dj_refresh.build_candidates", return_value={"songs": [song(i) for i in range(30)]}):
                result = refresh_all(c, d, h, hour=12345)
            self.assertTrue(all(v["status"] == "no_new_songs" for v in result.values()))
            self.assertEqual(before, {m: (d/f"{m}.json").read_bytes() for m in MODES})

    def test_24_hour_refresh_keeps_replacing_songs_when_catalog_allows(self):
        with tempfile.TemporaryDirectory() as root:
            c, d, h = self.setup_env(root)
            with patch("hourly_dj_refresh.build_candidates", return_value={"songs": [song(i) for i in range(80)]}):
                for hour in range(17000, 17024):
                    before = read_json(d/"hindi_90s.json", {})["songs"]
                    result = refresh_all(c, d, h, hour=hour)
                    after = read_json(d/"hindi_90s.json", {})["songs"]
                    self.assertEqual(result["hindi_90s"]["status"], "updated")
                    self.assertEqual(len(after), 30)
                    self.assertTrue(any(key(s) not in {key(p) for p in before} for s in after))
            self.assertEqual(len(read_json(h, {})["modes"]["hindi_90s"]["recent"]), 6)

    def test_mixed_outage_does_not_prevent_healthy_mode_update(self):
        with tempfile.TemporaryDirectory() as root:
            c, d, h = self.setup_env(root)
            old_ghazal = (d/"ghazal.json").read_bytes()
            def builder(mode, artist, providers, limit, per_query):
                if mode == "ghazal":
                    raise RuntimeError("temporary 429")
                return {"songs": [song(i) for i in range(80)]}
            with patch("hourly_dj_refresh.build_candidates", side_effect=builder):
                result = refresh_all(c, d, h, hour=12347)
            self.assertEqual(result["ghazal"]["status"], "source_unavailable")
            self.assertEqual(old_ghazal, (d/"ghazal.json").read_bytes())
            self.assertTrue(all(result[m]["status"] == "updated" for m in MODES if m != "ghazal"))

    def test_short_api_result_does_not_erase_last_good_json(self):
        with tempfile.TemporaryDirectory() as root:
            c, d, h = self.setup_env(root)
            before = (d/"romantic.json").read_bytes()
            with patch("hourly_dj_refresh.build_candidates", return_value={"songs": [song(42)]}):
                result = refresh_all(c, d, h, hour=12345)
            self.assertEqual(result["romantic"]["status"], "insufficient_valid_candidates")
            self.assertEqual(before, (d/"romantic.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
