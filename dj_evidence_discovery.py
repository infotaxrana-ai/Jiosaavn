#!/usr/bin/env python3
"""Pinpoint film playlist validation via Wikidata, fail-closed.

A song is accepted only when the source album maps unambiguously to a Hindi film
and the source film release date is 1970..2010. No on-device changes.
"""
import argparse
import concurrent.futures
import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ENDPOINT="https://www.wikidata.org/w/api.php"
FILM_TYPES={"Q11424","Q24869"} # film, feature film (not every subclass known)
HINDI="Q1568"
BAD_ALBUM=re.compile(r"\b(remix|jhankar|karaoke|cover|instrumental|hits of|best of|greatest hits|aarti|vol[\s.-]?\d+)\b",re.I)
SOUNDTRACK=re.compile(r"\s*\(\s*original\s+mo(?:s)?tion\s+picture\s+soundtrack\s*\)\s*",re.I)
USER_AGENT="XiaozhiDJMetadataReview/1.0 (research; read-only; GitHub Actions)"
def norm(s):
    s=html.unescape(str(s or "")).casefold()
    s=SOUNDTRACK.sub(" ",s)
    s=re.sub(r"\b(original\s+motion\s+picture\s+soundtrack|soundtrack\s+version)\b"," ",s)
    s=re.sub(r"[^a-z0-9]+"," ",s).strip()
    return " ".join(s.split())
def album_key(album):
    return norm(album)
def api(params):
    query=urllib.parse.urlencode({"format":"json",**params})
    req=urllib.request.Request(ENDPOINT+"?"+query,headers={"User-Agent":USER_AGENT,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=9) as resp:
        if urllib.parse.urlparse(resp.geturl()).netloc not in ("www.wikidata.org","wikidata.org"):
            raise ValueError("unexpected API redirect")
        b=resp.read(1_300_000)
        if len(b)>=1_300_000:raise ValueError("response too large")
        return json.loads(b)
def item_ids(claims, prop):
    found=set()
    for x in claims.get(prop,[]):
        value=x.get("mainsnak",{}).get("datavalue",{}).get("value",{})
        if isinstance(value,dict):
            q=value.get("id")
            if q:found.add(q)
    return found
def release_years(claims):
    years=set()
    for x in claims.get("P577",[]):
        v=x.get("mainsnak",{}).get("datavalue",{}).get("value",{})
        if not isinstance(v,dict):continue
        t=v.get("time","")
        m=re.match(r"^\+?(\d{4})-",t)
        if m:years.add(int(m.group(1)))
    return years
def titles(item):
    vals=[]
    for source in ("labels","aliases"):
        obj=item.get(source,{})
        for lang in ("en","hi"):
            value=obj.get(lang)
            if isinstance(value,dict):vals.append(value.get("value",""))
            elif isinstance(value,list):vals += [x.get("value","") for x in value]
    return [v for v in vals if v]
def evaluate(album, search, entities):
    matches=[]
    for hit in search.get("search",[]):
        item=entities.get(hit.get("id"),{})
        if not item or item.get("missing"):continue
        if album_key(album) not in {norm(t) for t in titles(item)}:continue
        claims=item.get("claims",{})
        desc=" ".join(
            item.get("descriptions",{}).get(lang,{}).get("value","")
            for lang in ("en","hi")).casefold()
        types=item_ids(claims,"P31")
        # Require P31 direct film or feature-film; don't infer from title.
        film=bool(types & FILM_TYPES)
        lang=item_ids(claims,"P364")
        hindi=HINDI in lang or (not lang and ("hindi-language film" in desc or "hindi film" in desc))
        yrs=release_years(claims)
        if not film or not hindi:continue
        if len(yrs)!=1:continue
        year=next(iter(yrs))
        matches.append({"qid":item["id"],"year":year,"film_name":next(iter(titles(item)),album),
                       "language_evidence":"P364 Hindi" if HINDI in lang else "English description Hindi film",
                       "source":"https://www.wikidata.org/wiki/"+item["id"]})
    uniq={m["qid"]:m for m in matches}
    valid=list(uniq.values())
    if len(valid)==1:return {"status":"matched",**valid[0]}
    if len(valid)>1:return {"status":"ambiguous","matches":valid}
    return {"status":"unverified","reason":"no unique Hindi film with matching title, P31 and release year"}
def lookup(album):
    if BAD_ALBUM.search(album):
        return {"status":"rejected","reason":"compilation/remix/non-film album marker"}
    search_name=re.sub(r"\s*\(\s*original\s+mo(?:s)?tion\s+picture\s+soundtrack\s*\)","",album,flags=re.I).strip()
    try:
        search=api({"action":"wbsearchentities","search":search_name,"language":"en","uselang":"en","limit":15})
        ids=[e["id"] for e in search.get("search",[]) if re.fullmatch(r"Q\d+",e.get("id",""))]
        if not ids:return {"status":"unverified","reason":"no Wikidata search results"}
        data=api({"action":"wbgetentities","ids":"|".join(ids),"props":"labels|aliases|descriptions|claims","languages":"en|hi"})
        return evaluate(search_name,search,data.get("entities",{}))
    except Exception as ex:
        return {"status":"unverified","reason":"Wikidata request failed: "+type(ex).__name__}

def run(report, workers=4):
    candidates=report.get("unverified_film_candidates",[])
    album_names=sorted({s.get("album","").strip() for s in candidates if isinstance(s,dict) and s.get("album")})
    print("Reviewing unique albums:",len(album_names),flush=True)
    matched={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(lookup,a):a for a in album_names}
        for n,future in enumerate(concurrent.futures.as_completed(futures),1):
            album=futures[future];matched[album]=future.result()
            if n%15==0:print("Wikidata checked",n,"/",len(album_names),flush=True)
    accepted=[];pending=[];seen=set();stats=Counter()
    for s in candidates:
        if not isinstance(s,dict):continue
        album=s.get("album","")
        match=matched.get(album,{"status":"unverified","reason":"album missing"})
        status=match["status"]
        if status!="matched":
            stats[status]+=1
            pending.append({**s,"review_reason":match.get("reason",status),"verification":"PENDING"})
            continue
        if not 1970<=match["year"]<=2010:
            stats["film_year_outside_range"]+=1
            continue
        # IDs are unique per physical recording, not per artist when same duet occurs multiple times.
        sid=s.get("id")
        unique=sid or (norm(s.get("title","")),album_key(album))
        if unique in seen:
            stats["duplicate_song_id"]+=1
            continue
        seen.add(unique)
        accepted.append({**s,"original_film_year":match["year"],
                         "verification":"WIKIDATA_FILM_METADATA",
                         "film_wikidata":match["source"],
                         "language_evidence":match["language_evidence"],
                         "artist_source":s.get("artist")})
        stats["accepted"]+=1
    return {"schema_version":2,"mode":"hindi_classic_movie_1970_2010",
            "preview_only":True,"filter_version":"film_catalog_full_v1",
            "accepted_film_candidates":accepted,"pending_or_unverified":pending,
            "album_validation":matched,"summary":dict(stats),
            "limitations":["Wikidata proves film title/year/language, not song-to-film association independently.",
                           "Original song language and artist credits require track-level confirmation.",
                           "Strict fail-closed: missing/ambiguous sources remain pending.",
                           "Stream/playability and ESP32 MCP compatibility are untested.",
                           "No publication or firmware changes."]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default="data/recovery_snapshot.json")
    p.add_argument("--output",default="dj_pinpoint_preview.json")
    p.add_argument("--workers",type=int,default=4)
    a=p.parse_args()
    if not 1<=a.workers<=6:raise SystemExit("workers 1..6")
    data=json.loads(Path(a.input).read_text(encoding="utf8"))
    result=run(data,a.workers)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("PINPOINT SUMMARY:",json.dumps(result["summary"]),flush=True)
    print("READ-ONLY. Not device-pass.",flush=True)
if __name__=="__main__":main()
