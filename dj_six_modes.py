#!/usr/bin/env python3
"""Standalone seven-mode DJ playlist builder for Xiaozhi JioSaavn.
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
 "kawali":[
  "Nusrat Fateh Ali Khan","Aziz Mian","Sabri Brothers",
  "Ghulam Farid Sabri","Maqbool Ahmed Sabri","Rahat Fateh Ali Khan",
  "Amjad Sabri","Fareed Ayaz","Rizwan-Muazzam Qawwali",
  "Wadali Brothers","Sher Miandad Khan","Javed Bashir"
 ],
 "bangla_classic":["Runa Laila","Sabina Yasmin","Andrew Kishore","Subir Nandi","Kanak Chapa","Manna Dey"]
}
QAWALI_WORD=re.compile(r"\b(?:qawwali|qawali|qawalli|kawwali|kawali)\b|قوالی|কাওয়ালি|কাওয়ালি",re.I)
QAWALI_TITLE_WORD=re.compile(r"\b(?:mast qalandar|dam mast qalandar|bhar do jholi|tajdar[ -]e[ -]haram|chaap tilak|allah hoo|tumhe dillagi|ye jo halka halka suroor hai|mere rashke qamar|sanson ki mala|man kunto maula)\b",re.I)
QAWALI_CATALOG_ARTISTS={norm(x) for x in (
 "Nusrat Fateh Ali Khan","Aziz Mian","Sabri Brothers","Ghulam Farid Sabri",
 "Maqbool Ahmed Sabri","Amjad Sabri","Fareed Ayaz","Rizwan-Muazzam Qawwali",
 "Wadali Brothers","Sher Miandad Khan"
)}
QAWALI_ARTIST_ALIASES={
 norm("Ghulam Farid Sabri"):{norm("Ghulam Farid Sabri Qawwal")},
 norm("Maqbool Ahmed Sabri"):{norm("Sabri Maqbool Ahmed"),norm("Maqbool Sabri")},
 norm("Fareed Ayaz"):{norm("Fareed Ayaz Abu Muhammad Qawwal"),norm("Fareed Ayaz Abu Mohammad Qawwal")},
 norm("Javed Bashir"):{norm("Jinx & Javed Bashir"),norm("Javed Bashir & Sharni")},
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
def artist_matches(candidate,target,mode):
    candidate=html.unescape(str(candidate or ""))
    if match_artist(candidate,target):return True
    if mode!="kawali":return False
    return norm(candidate) in QAWALI_ARTIST_ALIASES.get(norm(target),set())
def qawwali_singer_names(row):
    arts=row.get("artists") or {}
    names=[]
    if isinstance(arts,dict):
        for key in ("primary","featured"):
            for item in arts.get(key) or []:
                value=item.get("name","") if isinstance(item,dict) else str(item)
                value=html.unescape(value).strip()
                if value:names.append(value)
        if names:return list(dict.fromkeys(names))
        for key in ("primaryArtists","primary_artists","singers"):
            value=row.get(key)
            if isinstance(value,str):names.extend(html.unescape(x).strip() for x in re.split(r"[,;/|]+",value) if x.strip())
        return list(dict.fromkeys(names))
    return [html.unescape(x) for x in artist_names(row)]
def genre_context(row):
    return field(row,"genre","genres","tags","category","categories","type")
def mood_evidence(row,mode):
    # Enforce explicit mood evidence, NEVER infer emotion from singer.
    context=genre_context(row)+" | "+album(row)
    return bool(MOOD_WORDS[mode].search(context))
def mode_verdict(row,mode,query="",artist=""):
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
    if mode=="kawali":
        context=genre_context(row)+" | "+album(row)+" | "+field(row,"name","title")
        if QAWALI_WORD.search(context):return True,"qawwali_metadata"
        if QAWALI_TITLE_WORD.search(context):return True,"qawwali_known_track_title"
        if QAWALI_WORD.search(query):return True,"qawwali_search_query"
        if norm(artist) in QAWALI_CATALOG_ARTISTS:return True,"qawwali_artist_catalog"
        return False,"qawwali_unverified"
    if mode in MOOD_WORDS:
        if not mood_evidence(row,mode):return False,"mood_unverified"
        if lang in OTHER_LANGUAGE:return False,"language_mismatch"
        return True,"mood_label"
    return True,"artist_exact_match"

def search_specs(mode,artist):
    if mode=="artist_nonstop":return [artist]
    if mode=="kawali":return [artist+" qawwali",artist+" sufi qawwali",artist]
    suffix={"hindi_90s":"90s Hindi songs","romantic":"romantic songs","sad":"sad songs",
            "ghazal":"ghazal","bangla_classic":"Bangla songs"}[mode]
    return [artist+" "+suffix,artist]

def build(mode,artist,providers,limit=30,per_query=40,fixtures=None,seed=7):
    if mode not in set(ARTISTS)|{"artist_nonstop"}:raise ValueError("unknown mode")
    if mode=="artist_nonstop" and not artist:raise ValueError("artist is required")
    sources=[artist] if mode=="artist_nonstop" else ARTISTS[mode]
    buffers=[];checks={};errors={};seen_search=set()
    for target in sources:
        rows=[];counts=Counter();mismatch_examples=[];qawwali_unverified_examples=[]
        for q in search_specs(mode,target):
            try:
                if fixtures is not None:
                    src=Path(fixtures)/(re.sub(r"[^a-z0-9]+","_",q.casefold()).strip("_")+".json")
                    if not src.exists():continue
                    data=json.loads(src.read_text(encoding="utf8"))
                else:data=fetch_search(q,providers,per_query)
                rows.extend((row,q) for row in get_results(data))
            except Exception as ex:
                errors[q]=type(ex).__name__
        accepted=[]
        for row,query in rows:
            counts["total"]+=1
            if not isinstance(row,dict):continue
            sid=str(row.get("id") or "")
            artists=qawwali_singer_names(row) if mode=="kawali" else [html.unescape(x) for x in artist_names(row)]
            if not any(artist_matches(x,target,mode) for x in artists):
                counts["artist_mismatch"]+=1
                if mode=="kawali" and len(mismatch_examples)<3:
                    mismatch_examples.append({"title":row.get("name") or row.get("title"),"artists":artists,"query":query})
                continue
            url=audio_url(row)
            title=html.unescape(str(row.get("name") or row.get("title") or "")).strip()
            if not title or not url:
                counts["no_url_or_title"]+=1;continue
            key=sid or (norm(title),norm(album(row)),tuple(sorted(norm(a) for a in artists)))
            if key in seen_search:
                counts["duplicate"]+=1;continue
            seen_search.add(key)
            ok,evidence=mode_verdict(row,mode,query,target)
            if not ok:
                counts[evidence]+=1
                if mode=="kawali" and evidence=="qawwali_unverified" and len(qawwali_unverified_examples)<3:
                    qawwali_unverified_examples.append({"title":title,"album":album(row),"artists":artists,"query":query})
                continue
            accepted.append({"id":sid,"title":title,"artist":target,"actual_artists":artists,
                  "album":album(row),"year_metadata":extract_year(row),"language_metadata":explicit_language(row),
                  "evidence":evidence,"audio_url":url})
            counts["accepted"]+=1
        if mode=="hindi_90s":
            # Stable preference order: verified-range metadata first, others kept.
            accepted.sort(key=lambda x: x["evidence"] != "90s_catalog_year")
        audit_entry=dict(counts)
        if mode=="kawali":
            audit_entry["artist_mismatch_examples"]=mismatch_examples
            audit_entry["qawwali_unverified_examples"]=qawwali_unverified_examples
        checks[target]=audit_entry;buffers.append(deque(accepted))
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
         "Kawwali accepts exact artist credits with explicit Qawwali metadata or Qawwali-scoped search results; incomplete metadata can reduce coverage.",
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
