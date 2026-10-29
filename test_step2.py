import unittest
from build_dj import filter_songs

def song(id, name, artist, url='https://audio.example/audio.m4a'):
    return dict(id=id, name=name, artists={'primary':[{'name':artist}]},downloadUrl=[{'quality':'320kbps','url':url}])

class FilterTests(unittest.TestCase):
    def test_strict_artist_and_duplicate_and_missing(self):
        data={'success':True,'data':{'results':[
            song('1','Pehla Pyaar','Kumar Sanu'),
            song('2','Pehla Pyaar','Kumar Sanu'),
            song('3','Other Song','Udit Narayan'),
            song('4','Another','Kumar Sanu','not-valid-url'),
            song('5','Third','Kumar Shanu'),
            {'name':'Unknown','downloadUrl':[{'url':'https://audio.example/5.mp3'}]},
        ]}}
        result=filter_songs(data,'Kumar Sanu')
        self.assertEqual([x['title'] for x in result['songs']],['Pehla Pyaar','Third'])
        self.assertEqual(result['counts']['duplicate'],1)
        self.assertEqual(result['counts']['artist_mismatch'],1)
        self.assertEqual(result['counts']['no_audio'],1)
        self.assertEqual(result['counts']['no_artist'],1)
    def test_global_search_shape(self):
        result=filter_songs({'data':{'songs':{'results':[song('1','Test','Arijit Singh')]}}},'Arijit Singh')
        self.assertEqual(len(result['songs']),1)
if __name__=='__main__':unittest.main()
