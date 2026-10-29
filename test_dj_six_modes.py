import unittest
from dj_six_modes import build, mode_verdict
from pathlib import Path
import tempfile,json
def song(artist="Kumar Sanu",year=1995,language="Hindi",genre="Romantic",id="one"):
 return {"id":id,"name":"A love song","artists":{"primary":[{"name":artist}]},
 "year":year,"language":language,"genre":genre,"downloadUrl":[{"url":"https://example.org/x.mp4"}]}
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
 def test_artist(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/"kumar_sanu.json"
   f.write_text(json.dumps({"data":{"results":[song(),song(id="two",artist="Mohammed Rafi")]}}))
   out=build("artist_nonstop","Kumar Sanu",[],fixtures=d)
   self.assertEqual(out["playlist_count"],1)
   self.assertEqual(out["songs"][0]["artist"],"Kumar Sanu")
if __name__=="__main__":unittest.main()
