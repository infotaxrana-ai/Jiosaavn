#!/usr/bin/env python3
"""Read-only live JioSaavn candidate diagnostic. Never publishes playlists or contacts ESP32."""
import json, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

from build_dj import artist_names, match_artist, audio_url, get_results
from dj_six_modes import ARTISTS, search_specs, mode_verdict

def request_one(base, query, limit=30):
    url = base.rstrip("/") + "/api/search/songs?" + urllib.parse.urlencode({"query": query, "limit": limit})
    req = urllib.request.Request(url, headers={"User-Agent":"XiaozhiDJDiagnostic/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        if urllib.parse.urlparse(response.geturl()).scheme != "https":
            raise ValueError("unsafe redirect")
        raw=response.read(2_500_001)
        if len(raw)>2_500_000: raise ValueError("response too large")
        payload=json.loads(raw.decode("utf-8"))
        return payload, response.status, response.headers.get("content-type","")

def main():
    cfg=json.loads(Path("music_config.json").read_text(encoding="utf-8"))
    providers=[p for p in sorted(cfg.get("providers",[]),key=lambda x:x.get("priority",99)) if p.get("enabled") and str(p.get("base_url","")).startswith("https://")]
    report={"purpose":"read_only_live_api_diagnostic","providers":{},"note":"No playlist JSON, history, firmware, ESP32 or MCP Queue is modified."}
    for p in providers:
        name=p.get("name","provider"); priority=p.get("priority",99); base=p["base_url"].rstrip("/")
        pr={"name":name,"priority":priority,"base_url":base,"modes":{}}
        for mode, artists in ARTISTS.items():
            totals=Counter(); samples=[]; errors={}
            for artist in artists:
                for query in search_specs(mode,artist):
                    try:
                        payload,status,ctype=request_one(base,query,30)
                        rows=get_results(payload)
                        totals["http_ok"]+=1
                        totals["raw_results"]+=len(rows)
                        if not rows: totals["empty_results"]+=1
                        for row in rows:
                            if not isinstance(row,dict):
                                totals["invalid_row"]+=1; continue
                            names=artist_names(row)
                            matched=any(match_artist(a,artist) for a in names)
                            title=row.get("name") or row.get("title") or ""
                            downloads=row.get("downloadUrl") or row.get("download_url")
                            url=audio_url(row)
                            if matched: totals["artist_match"]+=1
                            else: totals["artist_mismatch"]+=1
                            if not title: totals["missing_title"]+=1
                            if not downloads: totals["missing_download_field"]+=1
                            if url: totals["accepted_48kbps_url"]+=1
                            else:
                                totals["rejected_audio_url"]+=1
                                if isinstance(downloads,list):
                                    for item in downloads:
                                        if isinstance(item,dict):
                                            totals["quality:"+str(item.get("quality","<missing>"))]+=1
                                elif isinstance(downloads,str): totals["download_field_string"]+=1
                            if matched and title and url:
                                ok,why=mode_verdict(row,mode)
                                totals["mode_filter_pass" if ok else "mode_filter_reject:"+why]+=1
                            if len(samples)<8:
                                samples.append({"query":query,"title":title,"artists":names[:5],
                                  "artist_match":matched,"download_field_type":type(downloads).__name__,
                                  "download_qualities":[x.get("quality") for x in downloads if isinstance(x,dict)] if isinstance(downloads,list) else [],
                                  "audio_url_48kbps_found":bool(url),"metadata_keys":sorted(row.keys())[:50]})
                    except Exception as e:
                        errors[query]=type(e).__name__+": "+str(e)[:180]
            pr["modes"][mode]={"counts":dict(totals),"errors":errors,"samples":samples}
        report["providers"][f"priority_{priority}"]=pr
        print(f"priority={priority} {name} ({base})", {m:v["counts"] for m,v in pr["modes"].items()}, flush=True)
    Path("dj_live_api_diagnostic.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("DIAGNOSTIC COMPLETE. Read-only; no playlist files changed.",flush=True)

if __name__=="__main__": main()
