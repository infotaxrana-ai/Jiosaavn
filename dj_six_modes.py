#!/usr/bin/env python3
"""Standalone six-mode DJ playlist builder for Xiaozhi JioSaavn.
Search metadata only; DOES NOT install, publish, or play on ESP32.
"""
import argparse, html, json, random, re
from collections import Counter, deque
from pathlib import Path
from build_dj import artist_names, match_artist, audio_url, get_results, norm
from build_dj_modes import extract_year, fetch_search, is_ghazal

ARTISTS={
 "hindi_90s":["Kumar Sanu","Udit Narayan","Alka Yagnik","Anuradha Paudwal","Abhijeet Bhattacharya"],
 "romantic":["Arijit Singh","Kumar Sanu","Udit Narayan","Shreya Ghoshal","Alka Yagnik","Sonu Nigam"],
 "sad":["Arijit Singh","Kumar Sanu","Sonu Nigam","Atif Aslam","Jagjit Singh"],
 "ghazal":["Jagjit Singh","Pankaj Udhas","Ghulam Ali","Talat Aziz"],
 "bangla_classic":["Runa Laila","Sabina Yasmin","Andrew Kishore","Subir Nandi","Kanak Chapa","Manna Dey"]
}
MOOD_WORDS={
 "romantic":re.compile(r"\b(romantic|romance|love|pyaar|pyar|prem|ishq|mohabbat)\b",re.I),
 "sad":re.compile(r"\b(sad|sadness|heartbreak|broken heart|dard|bewafa|judai|judaai|gham|virah)\b",re.I)
}
BANGLA_HINT=re.compile(r'[\u0980-\u09ff]|\b(bangla|bengali)\b',re.I)
OTHER_LANGUAGE={"tamil","telugu","kannada","malayalam","marathi","punjabi"}
def flatten(x):
    if isinstance(x,str):return [html.unescape(x)]
    if isinstance(x,dict):
        return sum((flatten(x.get(k)) for k in ("name","title","genre","language")),[])
    if isinstance(x,list):return sum((flatten(t) for t in x),[])
    return []
def field(row,*names):
    return " | ".join(z for n in names for z in flatten(row.get(n)))
def album(row):
    return field(row,"album")
def explicit_language(row):
    return field(row,"language","languages").casefold()
def genre_context(row):
    return field(row,"genre","genres","tags","category","categories","type")
def mood_evidence(row,mode):
    # Enforce explicit mood evidence, NEVER infer emotion from singer.
    context=genre_context(row)+" | "+album(row)
    return bool(MOOD_WORDS[mode].search(context))
def mode_verdict(row,mode):
    year=extract_year(row)
    lang=explicit_language(row)
    if mode=="hindi_90s":
        # Year is a *preference*, never a rejection reason: metadata may use
        # reissue years rather than the original recording or movie year.
        if lang and lang not in ("hindi","hi"):return False,"not_hindi"
        return True,("90s_catalog_year" if year is not None and 1990<=year<=1999
                     else "year_unknown_or_other_not_rejected")
    if mode=="bangla_classic":
        if lang and lang not in ("bengali","bangla","bn"):return False,"not_bengali"
        if not lang:return False,"language_unverified"
        return True,"bengali_metadata_and_artist"
    if mode=="ghazal":
        if not is_ghazal(row):return False,"ghazal_genre_unverified"
        return True,"ghazal_label"
    if mode in MOOD_WORDS:
        if not mood_evidence(row,mode):return False,"mood_unverified"
        if lang in OTHER_LANGUAGE:return False,"language_mismatch"
        return True,"mood_label"
    return True,"artist_exact_match"

def search_specs(mode,artist):
    if mode=="artist_nonstop":return [artist]
    suffix={"hindi_90s":"90s Hindi songs","romantic":"romantic songs","sad":"sad songs",
            "ghazal":"ghazal","bangla_classic":"Bangla songs"}[mode]
    return [artist+" "+suffix,artist]

def build(mode,artist,providers,limit=30,per_query=40,fixtures=None,seed=7):
    if mode not in set(ARTISTS)|{"artist_nonstop"}:raise ValueError("unknown mode")
    if mode=="artist_nonstop" and not artist:raise ValueError("artist is required")
    sources=[artist] if mode=="artist_nonstop" else ARTISTS[mode]
    buffers=[];checks={};errors={};seen_search=set()
    for target in sources:
        rows=[];counts=Counter()
        for q in search_specs(mode,target):
            try:
                if fixtures is not None:
                    src=Path(fixtures)/(re.sub(r"[^a-z0-9]+","_",q.casefold()).strip("_")+".json")
                    if not src.exists():continue
                    data=json.loads(src.read_text(encoding="utf8"))
                else:data=fetch_search(q,providers,per_query)
                rows+=get_results(data)
            except Exception as ex:
                errors[q]=type(ex).__name__
        accepted=[]
        for row in rows:
            counts["total"]+=1
            if not isinstance(row,dict):continue
            sid=str(row.get("id") or "")
            artists=artist_names(row)
            if not any(match_artist(x,target) for x in artists):
                counts["artist_mismatch"]+=1;continue
            url=audio_url(row)
            title=html.unescape(str(row.get("name") or row.get("title") or "")).strip()
            if not title or not url:
                counts["no_url_or_title"]+=1;continue
            key=sid or (norm(title),norm(album(row)),tuple(sorted(norm(a) for a in artists)))
            if key in seen_search:
                counts["duplicate"]+=1;continue
            seen_search.add(key)
            ok,evidence=mode_verdict(row,mode)
            if not ok:
                counts[evidence]+=1;continue
            accepted.append({"id":sid,"title":title,"artist":target,"actual_artists":artists,
                  "album":album(row),"year_metadata":extract_year(row),"language_metadata":explicit_language(row),
                  "evidence":evidence,"audio_url":url})
            counts["accepted"]+=1
        if mode=="hindi_90s":
            # Stable preference order: verified-range metadata first, others kept.
            accepted.sort(key=lambda x: x["evidence"] != "90s_catalog_year")
        checks[target]=dict(counts);buffers.append(deque(accepted))
    songs=[];seen=set()
    while len(songs)<limit and any(buffers):
        for buf in buffers:
            if not buf:continue
            track=buf.popleft()
            k=track["id"] or (norm(track["title"]),norm(track["album"]))
            if k in seen:continue
            seen.add(k);songs.append(track)
            if len(songs)>=limit:break
    return {"schema_version":1,"preview_only":True,"mode":mode,"requested_artist":artist if mode=="artist_nonstop" else None,
         "playlist_count":len(songs),"songs":songs,"audit":checks,"fetch_errors":errors,
         "limitations":["Mood and ghazal classification use metadata labels; unlabeled valid songs are excluded.",
         "1990s uses catalog year for ranking only; no song is rejected for missing/outside-range year, and some selections may not be from the 1990s.",
         "Artist match allows collaborations if the requested artist appears in the credits.",
         "Audio URLs and playback are NOT tested; existing ESP32 Queue is unchanged."]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",required=True,choices=["artist_nonstop"]+list(ARTISTS))
    p.add_argument("--artist",default="")
    p.add_argument("--limit",type=int,default=30)
    p.add_argument("--per-query",type=int,default=40)
    p.add_argument("--fixtures")
    p.add_argument("--config",default="music_config.json")
    p.add_argument("--output",default="dj_six_modes_preview.json")
    a=p.parse_args()
    if not 1<=a.limit<=200 or not 1<=a.per_query<=100:raise SystemExit("invalid limits")
    cfg=json.loads(Path(a.config).read_text(encoding="utf8"))
    providers=[x["base_url"] for x in sorted(cfg["providers"],key=lambda x:x.get("priority",99))
               if x.get("enabled") and str(x.get("base_url","")).startswith("https://")]
    out=build(a.mode,a.artist,providers,a.limit,a.per_query,a.fixtures)
    Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("DJ SIX MODES",a.mode,"accepted",out["playlist_count"],flush=True)
    print("SOURCE AUDIT:",json.dumps(out["audit"]),flush=True)
    print("READ-ONLY preview. Firmware unchanged.",flush=True)
if __name__=="__main__":main()
