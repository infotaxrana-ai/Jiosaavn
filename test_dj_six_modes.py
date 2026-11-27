import unittest
from dj_six_modes import build, mode_verdict, search_specs
from pathlib import Path
import tempfile,json
def song(artist="Kumar Sanu",year=1995,language="Hindi",genre="Romantic",id="one"):
 return {"id":id,"name":"A love song","artists":{"primary":[{"name":artist}]},
 "year":year,"language":language,"genre":genre,"downloadUrl":[{"quality":"48kbps","url":"https://example.org/x_48.mp4"}]}
class DJTests(unittest.TestCase):
 def test_year(self):
  self.assertTrue(mode_verdict(song(),"hindi_90s")[0])
  self.assertTrue(mode_verdict(song(year=2000),"hindi_90s")[0])
  self.assertTrue(mode_verdict(song(year=None),"hindi_90s")[0])
  self.assertFalse(mode_verdict(song(language="Tamil"),"hindi_90s")[0])
 def test_bangla(self):
  self.assertTrue(mode_verdict(song(language="Bengali"),"bangla_classic")[0])
  self.assertFalse(mode_verdict(song(language="Tamil"),"bangla_classic")[0])
 def test_mood_not_assumed(self):
  self.assertFalse(mode_verdict(song(genre="Pop"),"romantic")[0])
  self.assertTrue(mode_verdict(song(genre="Romantic"),"romantic")[0])
 def test_ghazal(self):
  self.assertTrue(mode_verdict(song(genre="Ghazal"),"ghazal")[0])
  self.assertFalse(mode_verdict(song(genre="pop"),"ghazal")[0])
 def test_kawali_requires_qawwali_evidence_or_scoped_search(self):
  self.assertTrue(mode_verdict(song(artist="Nusrat Fateh Ali Khan",genre="Qawwali"),"kawali")[0])
  self.assertFalse(mode_verdict(song(artist="Nusrat Fateh Ali Khan",genre="Pop"),"kawali")[0])
  self.assertTrue(mode_verdict(song(artist="Nusrat Fateh Ali Khan",genre="Pop"),"kawali","Nusrat Fateh Ali Khan qawwali")[0])
  self.assertEqual(search_specs("kawali","Nusrat Fateh Ali Khan"),[
   "Nusrat Fateh Ali Khan qawwali","Nusrat Fateh Ali Khan sufi qawwali","Nusrat Fateh Ali Khan"])
 def test_kawali_known_qawwal_catalog_and_known_track(self):
  self.assertTrue(mode_verdict(song(artist="Sher Miandad Khan",genre="Pop"),"kawali",artist="Sher Miandad Khan")[0])
  self.assertFalse(mode_verdict(song(artist="Rahat Fateh Ali Khan",genre="Pop"),"kawali",artist="Rahat Fateh Ali Khan")[0])
  track=song(artist="Rahat Fateh Ali Khan",genre="Pop")
  track["name"]="Mast Qalandar"
  self.assertTrue(mode_verdict(track,"kawali",artist="Rahat Fateh Ali Khan")[0])
 def test_artist(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/"kumar_sanu.json"
   f.write_text(json.dumps({"data":{"results":[song(),song(id="two",artist="Mohammed Rafi")]}}))
   out=build("artist_nonstop","Kumar Sanu",[],fixtures=d)
   self.assertEqual(out["playlist_count"],1)
   self.assertEqual(out["songs"][0]["artist"],"Kumar Sanu")
 def test_kawali_ignores_composer_only_credit(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/"maqbool_ahmed_sabri_qawwali.json"
   row=song(artist="Ayisha Abdul Basith",genre="Qawwali")
   row["artists"]={"primary":[{"name":"Ayisha Abdul Basith"}],
                   "all":[{"name":"Ayisha Abdul Basith"},{"name":"Sabri Maqbool Ahmed"}]}
   f.write_text(json.dumps({"data":{"results":[row]}}))
   out=build("kawali","",[],fixtures=d)
   self.assertEqual(out["playlist_count"],0)
 def test_kawali_alias_matches_fareed_ayaz_qawwal_credit(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/"fareed_ayaz_qawwali.json"
   f.write_text(json.dumps({"data":{"results":[
    song(artist="Fareed Ayaz Abu Muhammad Qawwal",genre="Pop")
   ]}}))
   out=build("kawali","",[],fixtures=d)
   self.assertEqual(out["playlist_count"],1)
   self.assertEqual(out["songs"][0]["artist"],"Fareed Ayaz")
 def test_kawali_fixture_build_keeps_exact_qawwali_artist(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/"nusrat_fateh_ali_khan_qawwali.json"
   f.write_text(json.dumps({"data":{"results":[
    song(artist="Nusrat Fateh Ali Khan",genre="Pop"),
    song(artist="Kumar Sanu",genre="Qawwali",id="other")
   ]}}))
   out=build("kawali","",[],fixtures=d)
   self.assertEqual(out["playlist_count"],1)
   self.assertEqual(out["songs"][0]["artist"],"Nusrat Fateh Ali Khan")
if __name__=="__main__":unittest.main()
