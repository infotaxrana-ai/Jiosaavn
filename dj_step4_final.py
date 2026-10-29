#!/usr/bin/env python3
"""Read-only DJ classic candidate validation. Never claims general film verification.
Uses curated exact title+album+original-year examples; all other candidates remain unverified.
"""
import json, re, argparse, html
from pathlib import Path
from collections import Counter
from build_dj import norm

# These examples are explicitly reviewed movie/song pairings, NOT a comprehensive movie DB.
# Keep an explicit original film year, distinct from a search service's release_year.
CURATED = [
 ('O Mere Dil Ke Chain','Mere Jeevan Saathi',1972),
 ('Yeh Vaada Raha','Yeh Vaada Raha',1982),
 ('Kehdoon Tumhen','Deewaar',1975),
 ('Dekha Ek Khwab','Silsila',1981),
 ('Tere Bina Zindagi Se','Aandhi',1975),
 ('Bheegi Bheegi Raaton Mein','Ajanabee',1974),
 ('Kya Yahi Pyar Hai','Rocky',1981),
 ('Chhu Kar Mere Manko','Yaarana',1981),
 ('Tere Chehre Se Nazar Nahin','Kabhi Kabhie',1976),
 ('Ek Ajnabee Haseena Se','Ajanabee',1974),
 ('Panna Ki Tamanna Hai','Heera Panna',1973),
 ('Zindagi Ki Yahi Reet Hai','Mr. India',1987),
 ('Chura Liya Hai Tumne Jo Dil Ko','Yaadon Ki Baaraat',1973),
 ('Kya Hua Tera Vada','Hum Kisise Kum Naheen',1977),
 ('Kahin Door Jab Din Dhal Jaye','Anand',1971),
 ('Ek Pyar Ka Naghma Hai','Shor',1972),
 ('Kya Khoob Lagti Ho','Dharmatma',1975),
 ('Tujhe Dekha To','Dilwale Dulhania Le Jayenge',1995),
 ('Mehndi Laga Ke Rakhna','Dilwale Dulhania Le Jayenge',1995),
 ('Dil To Pagal Hai','Dil To Pagal Hai',1997),
 ('Tere Liye','Veer-Zaara',2004),
 ('Aankhein Khuli','Mohabbatein',2000),
 ('Main Agar Kahoon','Om Shanti Om',2007),
 ('Chori Kiya Re Jiya','Dabangg',2010),
 ('Dheere Dheere Se Meri Zindagi Mein Aana','Aashiqui',1990),
 ('Kisi Ki Muskurahaton Se','Anari',1959),
 ('Ae Mere Humsafar','Qayamat Se Qayamat Tak',1988),
 ('Baazigar O Baazigar','Baazigar',1993),
 ('Bole Chudiyan','Kabhi Khushi Kabhie Gham',2001),
 ('Koi Mil Gaya','Kuch Kuch Hota Hai',1998),
 ('Pehli Pehli Baar Mohabbat Ki Hai','Sirf Tum',1999),
]

def clean_title(s):
    s=html.unescape(s or '')
    s=re.sub(r'\s*\(From\s+["“].*?["”]\)','',s,flags=re.I)
    s=re.sub(r'\s*\([^)]*(?:Soundtrack Version|Duet Version|Solo Version)\)','',s,flags=re.I)
    s=re.sub(r'\s*-\s*(?:II|III|Part\s*[0-9]+)$','',s,flags=re.I)
    return norm(s)

LOOKUP={(clean_title(t),norm(a)):(t,a,y) for t,a,y in CURATED}

# Only publish in 'curated_review_candidates', never claim stream or metadata fully validated.
def process(report):
    selected=[];needs_review=[];excluded=[];seen=set();count=Counter()
    for s in report.get('unverified_film_candidates',[]):
        if not isinstance(s,dict): continue
        title=s.get('title','');album=s.get('album','')
        key=(clean_title(title),norm(album))
        entry=LOOKUP.get(key)
        if entry:
            original=entry[2]
            song={**s,'original_film_year_curated':original,'film_evidence':'locally_curated_title_album_pair','original_release_year_verified_externally':False}
            if not 1970<=original<=2010:
                excluded.append({'title':title,'album':album,'reason':'original_film_year_out_of_range','original_film_year':original})
                count['curated_out_of_range']+=1
                continue
            dedup=s.get('id') or (key)
            if dedup in seen: count['duplicate']+=1;continue
            seen.add(dedup)
            selected.append(song);count['curated_in_range']+=1
        else:
            needs_review.append({**s,'reason':'film/language/original_year_not_verified'})
            count['needs_review']+=1
    return {'schema_version':1,'preview_only':True,'mode':report.get('mode'),
      'curated_review_candidates':selected,'unverified_remaining':needs_review,'excluded':excluded,
      'summary':dict(count), 'device_integration':'NOT_IMPLEMENTED',
      'warnings':['Curated matches are not independently revalidated during the run.',
                  'Hindi language and playback capability are NOT verified.',
                  'Never treat year-only entries as verified movies.',
                  'No firmware, MCP, news or alarm changes.']}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--output',default='dj_step4_final_preview.json')
    a=ap.parse_args()
    output=process(json.loads(Path(a.input).read_text(encoding='utf-8')))
    Path(a.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('STEP4 FINAL REVIEW',json.dumps(output['summary']))
    print('READ-ONLY; no ESP32/DJ queue integration')
if __name__=='__main__':main()
