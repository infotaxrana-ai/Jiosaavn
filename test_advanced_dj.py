import unittest
from advanced_dj import build
def row(title,artist,year=None,album="Film",genre=None):
    r={"name":title,"id":title,"artists":{"primary":[{"name":artist}]},"album":{"name":album},
       "downloadUrl":[{"url":"https://audio.example/"+title.replace(" ","")+".mp4"}]}
    if year is not None:r["year"]=year
    if genre:r["genre"]=genre
    return r
def search_fixture(rows):
    return lambda q,n,p:{"data":{"results":rows}} if p==0 else {"data":{"results":[]}}
class DJTests(unittest.TestCase):
    def test_artist_strict(self):
        r=build("artist","Kumar Sanu",10,searcher=search_fixture([row("A","Kumar Sanu"),row("B","Arijit Singh")]))
        self.assertEqual([x["title"] for x in r["songs"]],["A"])
    def test_90s(self):
        r=build("90s",limit=10,searcher=search_fixture([row("A","Kumar Sanu",1995),row("B","Kumar Sanu",2012),row("C","Kumar Sanu")]))
        self.assertEqual([x["title"] for x in r["songs"]],["A"])
    def test_ghazal_requires_evidence(self):
        r=build("ghazal",limit=10,searcher=search_fixture([row("A","Jagjit Singh",genre="Ghazal"),row("B","Jagjit Singh",genre="Pop")]))
        self.assertEqual([x["title"] for x in r["songs"]],["A"])
    def test_romantic(self):
        r=build("romantic",limit=5,searcher=search_fixture([row("A","Singer",album="Romantic Hits"),row("B","Singer",album="Dance Hits")]))
        self.assertEqual([x["title"] for x in r["songs"]],["A"])
    def test_sad(self):
        r=build("sad",limit=5,searcher=search_fixture([row("A","Singer",genre="Sad Songs"),row("B","Singer",genre="Party")]))
        self.assertEqual([x["title"] for x in r["songs"]],["A"])
    def test_dedup(self):
        r=build("artist","Kumar Sanu",20,searcher=search_fixture([row("A","Kumar Sanu"),row("A","Kumar Sanu")]))
        self.assertEqual(r["playlist_count"],1)
if __name__=="__main__":unittest.main()
