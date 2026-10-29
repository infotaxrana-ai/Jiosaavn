#!/usr/bin/env python3
"""Xiaozhi Advanced DJ v1. Safe standalone queue creator; no firmware changes.

Modes: artist, 90s, romantic, sad, ghazal.
Artist mode requires exact singer credit. Mood modes use explicit contextual
evidence (genre/tag/album/title); missing mood metadata is rejected.
"""
import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict, deque
from pathlib import Path

from build_dj import audio_url, artist_names, get_results, match_artist, norm
from build_dj_modes import extract_year, labels

DEFAULT_ARTISTS=["Kumar Sanu","Udit Narayan","Alka Yagnik","Lata Mangeshkar","Arijit Singh","Shreya Ghoshal"]
GHAZAL_ARTISTS=["Jagjit Singh","Pankaj Udhas","Ghulam Ali","Talat Aziz"]
MOOD_TERMS={
 "romantic": re.compile(r"\b(romantic|romance|love songs?|love hits?|pyar|pyaar|ishq|mohabbat|প্রেম|ভালোবাসা)\b",re.I),
 "sad": re.compile(r"\b(sad|heartbreak|broken heart|melanchol|painful|dard|bewafa|judai|judaai|বিরহ|দুঃখ)\b",re.I),
 "ghazal": re.compile(r"\bghazals?\b|গ[জয]ল|غزل",re.I),
}
NON_ORIGINAL=re.compile(r"\b(remix|cover|karaoke|instrumental|lofi|lo-fi|slowed|reverb|mashup)\b",re.I)

def full_text(row):
    album=row.get("album")
    albumname=(album.get("name") or album.get("title") or "") if isinstance(album,dict) else str(album or "")
    return " | ".join([html.unescape(row.get("name") or row.get("title") or ""),
        html.unescape(albumname),
        labels(row,("genre","genres","tags","category","categories","type"))])

def metadata_mood_evidence(row,mode):
    album=row.get("album")
    albumname=(album.get("name") or album.get("title") or "") if isinstance(album,dict) else str(album or "")
    genre=labels(row,("genre","genres","tags","category","categories","type"))
    # Song titles contain many love / sad words; only album-level playlist
    # labels and explicit genre/tags are acceptable. Do not assume from artist.
    ev=" | ".join((genre, albumname))
    return bool(MOOD_TERMS[mode].search(html.unescape(ev)))

def providers_from_config(path):
    cfg=json.loads(Path(path).read_text(encoding="utf-8"))
    return [v["base_url"].rstrip("/") for v in sorted(cfg.get("providers",[]),key=lambda v:v.get("priority",99))
        if v.get("enabled") and isinstance(v.get("base_url"),str)
        and urllib.parse.urlsplit(v["base_url"]).scheme=="https"]

def fetch(query,providers,limit=50,page=0):
    errors=[]
    for base in providers:
        url=base+"/api/search/songs?"+urllib.parse.urlencode({"query":query,"limit":limit,"page":page})
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"XiaozhiAdvancedDJ/1.0","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=10) as res:
                if urllib.parse.urlsplit(res.geturl()).scheme!="https":raise ValueError("insecure redirect")
                raw=res.read(2_000_001)
                if len(raw)>2_000_000:raise ValueError("oversized response")
                data=json.loads(raw)
                if get_results(data):return data
                errors.append("empty:"+base)
        except (OSError,ValueError,TypeError) as e:
            errors.append(type(e).__name__+":"+base)
    raise RuntimeError("; ".join(errors))

def search_plan(mode,artist):
    if mode=="artist":
        if not artist or not artist.strip():raise ValueError("--artist is required for artist mode")
        return [(artist,artist)]
    if mode=="90s":
        return [(a,a) for a in DEFAULT_ARTISTS[:4]]
    if mode=="ghazal":
        return [(a+" ghazal",a) for a in GHAZAL_ARTISTS]
    terms={"romantic":["romantic songs","love songs","romantic hits"],
           "sad":["sad songs","heartbreak songs","sad hits"]}[mode]
    return [(q,None) for q in terms]

def candidate(row,mode,target,seen_count):
    if not isinstance(row,dict):return None,"invalid"
    names=artist_names(row)
    if not names:return None,"missing_artist"
    if mode=="artist" and not any(match_artist(n,target) for n in names):
        return None,"artist_mismatch"
    if mode=="ghazal" and target and not any(match_artist(n,target) for n in names):
        return None,"artist_mismatch"
    url=audio_url(row)
    title=html.unescape(row.get("name") or row.get("title") or "")
    if not title or not url:return None,"missing_audio_or_title"
    if NON_ORIGINAL.search(title):return None,"non_original_version"
    year=extract_year(row)
    if mode=="90s":
        if year is None:return None,"year_missing"
        if year<1990 or year>1999:return None,"year_outside_1990_1999"
    if mode in MOOD_TERMS and not metadata_mood_evidence(row,mode):
        return None,"mood_or_genre_unverified"
    album=row.get("album")
    album=(album.get("name") or album.get("title") or "") if isinstance(album,dict) else str(album or "")
    return {"id":str(row.get("id") or ""),"title":title,"artist":names[0],
      "all_artists":names,"album":html.unescape(album),"api_release_year":year,
      "audio_url":url,"evidence":{"artist_credit":"JioSaavn search metadata",
      "mode_rule":"strict singer credit" if mode=="artist" else
         "search release-year 1990-1999" if mode=="90s" else
         "explicit genre/album keyword metadata"}},None

def build(mode,artist="",limit=60,providers=None,searcher=None):
    if mode not in ("artist","90s","romantic","sad","ghazal"):raise ValueError("bad mode")
    if not 1<=limit<=200:raise ValueError("limit must be 1..200")
    plan=search_plan(mode,artist)
    fetcher=searcher or (lambda q,n,p:fetch(q,providers or [],n,p))
    audit=Counter(); queues=[];errors=[]
    for query,target in plan:
        tracks=[]
        for page in range(2):
            try:
                payload=fetcher(query,50,page)
            except (RuntimeError,OSError,ValueError) as e:
                errors.append({"query":query,"page":page,"error":type(e).__name__})
                break
            rows=get_results(payload)
            if not rows:break
            for row in rows:
                item,reason=candidate(row,mode,target,audit)
                if reason:audit[reason]+=1
                else:tracks.append(item)
            if len(rows)<50:break
        queues.append(deque(tracks))
    unique_ids=set(); unique_url=set();unique_titles=set()
    chosen=[]
    while len(chosen)<limit and any(queues):
        for q in queues:
            if not q:continue
            song=q.popleft()
            # Identical song by ID/URL collapsed, but don't collapse different recordings.
            song_id=song["id"];url=song["audio_url"]
            title_key=(norm(song["title"]),norm(song["album"]))
            if (song_id and song_id in unique_ids) or url in unique_url or title_key in unique_titles:
                audit["duplicate"]+=1;continue
            if song_id:unique_ids.add(song_id)
            unique_url.add(url);unique_titles.add(title_key)
            chosen.append(song)
            if len(chosen)>=limit:break
    return {"schema_version":1,"preview_only":True,"mode":mode,
       "artist_request":artist if mode=="artist" else None,
       "playlist_count":len(chosen),"songs":chosen,
       "audit":dict(audit),"provider_errors":errors,
       "limitations":[
          "Artist matching uses source credits; metadata can be wrong.",
          "90s filter uses JioSaavn release year, which may be a reissue, not original song/film year.",
          "Romantic/Sad/Ghazal require explicit album or genre terms; incomplete metadata reduces coverage.",
          "Audio URLs are untested; device queue integration and continuous refill are NOT implemented.",
          "No firmware/music/alarms/news changes."]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",required=True,choices=("artist","90s","romantic","sad","ghazal"))
    p.add_argument("--artist",default="")
    p.add_argument("--limit",type=int,default=60)
    p.add_argument("--config",default="music_config.json")
    p.add_argument("--output",default="advanced_dj_preview.json")
    a=p.parse_args()
    result=build(a.mode,a.artist,a.limit,providers_from_config(a.config))
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ADVANCED_DJ:",json.dumps({"mode":a.mode,"songs":result["playlist_count"],
      "audit":result["audit"],"errors":result["provider_errors"]},ensure_ascii=False),flush=True)
    print("PREVIEW ONLY, no firmware modifications",flush=True)
if __name__=="__main__":main()
