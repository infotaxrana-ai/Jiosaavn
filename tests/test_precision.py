import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from precision_gate import run, inventory
class GateTest(unittest.TestCase):
 def setUp(self):
  self.src={'unverified_film_candidates':[{'id':'1','title':'Nice Song','album':'Nice Movie','artist':'Artist','audio_url':'https://host.example/test.mp4','release_year_not_film_year':1985}]}
  self.record={'decision':'approve','original_film_year':1985,'film_title':'Nice Movie','evidence_urls':['https://imdb.com/title/tt1','https://wikidata.org/wiki/Q2'],'confirmed':dict.fromkeys(('song_to_film','original_film_year','hindi_language','singer_credits','recording_identity','licensing_rights'),True),'device_playback_test':True}
 def test_no_approval_without_review(self):self.assertEqual(len(run(self.src,{})['device_verified_tracks']),0)
 def test_with_two_sources_and_all_claims(self):self.assertEqual(len(run(self.src,{'1':self.record})['device_verified_tracks']),1)
 def test_no_second_source(self):self.assertEqual(len(run(self.src,{'1':{**self.record,'evidence_urls':['https://wikidata.org/wiki/Q1']}})['device_verified_tracks']),0)
 def test_no_device(self):self.assertEqual(len(run(self.src,{'1':{**self.record,'device_playback_test':False}})['device_verified_tracks']),0)
 def test_bad_year(self):self.assertEqual(len(run(self.src,{'1':{**self.record,'original_film_year':1960}})['device_verified_tracks']),0)
 def test_duplicate_id(self):self.assertEqual(len(inventory({'unverified_film_candidates':[self.src['unverified_film_candidates'][0]]*2})),1)
if __name__=='__main__':unittest.main()
