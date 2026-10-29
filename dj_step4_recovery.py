#!/usr/bin/env python3
"""Read-only Step 4 recovery: rank film-evidence and year evidence separately.
Never represents year-only songs as verified Hindi film songs.
No device calls, firmware updates, or repository publishing.
"""
import argparse
import json
from collections import Counter
from pathlib import Path
from build_dj import get_results, filter_songs, norm
from build_dj_modes import MODES, extract_year, is_hindi_movie, fetch_search

def review(payload, artist):
    accepted = filter_songs(payload, artist, max_items=120)["songs"]
    original = get_results(payload)
    byid = {str(v["id"]):v for v in original if isinstance(v,dict) and v.get("id") is not None}
    counts=Counter()
    rows=[]
    for x in accepted:
        meta=byid.get(str(x["id"])) if x.get("id") is not None else None
        if meta is None:
            matches=[v for v in original if isinstance(v,dict) and norm(v.get("name") or v.get("title"))==norm(x["title"])]
            if len(matches)==1: meta=matches[0]
        if meta is None:
            counts["unresolved_metadata"]+=1
            continue
        year=extract_year(meta)
        if year is None or not 1970<=year<=2010:
            counts["missing_or_outside_release_year"]+=1
            continue
        # The release year is NOT necessarily original film year.
        album=meta.get("album")
        album_name=(album.get("name") or album.get("title") or "") if isinstance(album,dict) else str(album or "")
        explicit_film=is_hindi_movie(meta)
        tier="explicit_film_metadata" if explicit_film else "year_only_unverified_film"
        counts[tier]+=1
        rows.append({
            "id":x.get("id"),"title":x["title"],"artist":artist,
            "release_year_not_film_year":year, "album":album_name,
            "film_metadata_explicit":explicit_film,"verification_tier":tier,
            "audio_url":x["audio_url"]
        })
    return rows,dict(counts)

def build(providers, max_per_artist=40):
    out={"schema_version":1,"mode":"hindi_classic_movie_1970_2010",
         "preview_only":True,"verified_film_tracks":[],"unverified_film_candidates":[],
         "artist_audit":{},"errors":{},"limitations":[
             "Search release year can be remaster/re-release; it is not verified original film year.",
             "Year-only candidates are NOT confirmed Hindi film songs.",
             "Playable audio, language and ESP32/MCP compatibility have NOT been checked.",
             "No change to firmware, streaming, news, alarms or music configuration."]}
    seen=set()
    for artist in MODES["hindi_classic_movie_1970_2010"]:
        try:
            payload=fetch_search(artist, providers, max_per_artist)
            rows,counts=review(payload,artist)
            out["artist_audit"][artist]=counts
            for row in rows:
                key=(norm(row["title"]),norm(row["artist"]))
                if key in seen: continue
                seen.add(key)
                if row["film_metadata_explicit"]:out["verified_film_tracks"].append(row)
                else:out["unverified_film_candidates"].append(row)
            print(artist,counts,flush=True)
        except Exception as exc:
            out["errors"][artist]=type(exc).__name__
            print(artist,"ERROR",type(exc).__name__,flush=True)
    out["summary"]={"explicit_film_metadata":len(out["verified_film_tracks"]),
                    "year_only_unverified":len(out["unverified_film_candidates"]),
                    "api_errors":len(out["errors"])}
    out["integration_status"]="BLOCKED_PENDING_FILM_YEAR_AND_DEVICE_VERIFICATION"
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",default="music_config.json")
    p.add_argument("--output",default="dj_step4_recovery_preview.json")
    p.add_argument("--limit",type=int,default=40)
    a=p.parse_args()
    if not 1<=a.limit<=100:raise SystemExit("limit must be 1..100")
    cfg=json.loads(Path(a.config).read_text(encoding="utf-8"))
    providers=[v["base_url"] for v in sorted(cfg["providers"],key=lambda z:z.get("priority",99))
               if v.get("enabled") and str(v.get("base_url","")).startswith("https://")]
    if not providers:raise SystemExit("No enabled HTTPS providers")
    result=build(providers,a.limit)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("STEP4_RECOVERY",json.dumps(result["summary"]),flush=True)
    print("PREVIEW ONLY. No changes to device or existing DJ logic.",flush=True)

if __name__=="__main__":main()
