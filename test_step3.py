import unittest
from build_dj_modes import extract_year, is_ghazal, is_hindi_movie, candidates, build

def song(title,artist,year=None,genre=None,movie=None):
    d={'id':title,'name':title,'artists':{'primary':[{'name':artist}]},'downloadUrl':[{'quality':'48kbps','url':'https://audio.example/'+title.replace(' ','-')+'.mp3'}]}
    if year is not None: d['year']=year
    if genre: d['genre']=genre
    if movie: d['movie']=movie
    return d

def payload(songs): return {'data':{'results':songs}}
class Tests(unittest.TestCase):
    def test_year(self):
        self.assertEqual(extract_year({'releaseDate':'1998-04-04'}),1998)
        self.assertIsNone(extract_year({'year':'unknown'}))
        self.assertIsNone(extract_year({'year':1998,'releaseDate':'2000-04-04'}))
    def test_90s(self):
        songs,c=candidates(payload([song('A','Kumar Sanu',1996),song('B','Kumar Sanu',1980),song('C','Kumar Sanu')]),'Kumar Sanu','hindi_90s_mix',30)
        self.assertEqual([x['title'] for x in songs],['A'])
        self.assertEqual(c['missing_year'],1)
        self.assertEqual(c['outside_year_range'],1)
    def test_ghazal(self):
        songs,c=candidates(payload([song('G','Pankaj Udhas',genre='Ghazal'),song('P','Pankaj Udhas',genre='Pop')]),'Pankaj Udhas','ghazal_mix',30)
        self.assertEqual(len(songs),1)
        self.assertEqual(c['genre_unverified'],1)
    def test_classic_film(self):
        songs,c=candidates(payload([song('A','Kishore Kumar',1970,movie='Film A'),song('B','Kishore Kumar',2010,movie='Film B'),song('C','Kishore Kumar',2011,movie='Film C'),song('D','Kishore Kumar',1985)]),'Kishore Kumar','hindi_classic_movie_1970_2010',30)
        self.assertEqual([x['title'] for x in songs],['A','B'])
        self.assertEqual(c['film_unverified'],1)
        self.assertEqual(c['outside_year_range'],1)
    def test_no_files_safe(self):
        r=build('ghazal_mix',fixture_dir='/nonexistent/folder')
        self.assertEqual(r['playlist_count'],0)
        self.assertTrue(r['preview_only'])
if __name__ == '__main__': unittest.main()
