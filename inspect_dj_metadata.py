#!/usr/bin/env python3
"""Read-only Xiaozhi DJ metadata diagnostic; never writes playlist or firmware."""
import argparse
import json
from collections import Counter
from pathlib import Path
from build_dj_modes import MODES, fetch_search, get_results, extract_year, is_hindi_movie, is_ghazal, labels
from build_dj import artist_names, match_artist


def run(mode, limit, output):
    cfg = json.loads(Path('music_config.json').read_text(encoding='utf8'))
    providers = [v['base_url'] for v in sorted(cfg['providers'], key=lambda p:p['priority']) if v_enabled(v)]
    report = {'mode':mode,'purpose':'read_only_metadata_diagnostic','artists':{},'summary':{},'limitations':[
        'Search release year may denote re-release or remaster instead of original film year.',
        'Album title without confirmed film identity does NOT establish movie soundtrack.',
        'No audio playback or ESP32/MCP validation.']}
    totals = Counter()
    for artist in MODES[mode]:
        try:
            response = fetch_search(artist, providers, limit)
            rows = get_results(response)
            counts = Counter()
            samples = []
            for row in rows:
                if not isinstance(row, dict):
                    counts['invalid'] += 1
                    continue
                year = extract_year(row)
                matched = any(match_artist(a,artist) for a in artist_names(row))
                movie = is_hindi_movie(row)
                counts['total'] += 1
                counts['artist_matched' if matched else 'artist_mismatch'] += 1
                counts['film_marked' if movie else 'film_unverified'] += 1
                counts['year_1970_2010' if year is not None and 1970 <= year <= 2010 else 'other_or_missing_year'] += 1
                if len(samples)<10 or (matched and movie and year is not None and 1970<=year<=2010 and len(samples)<16):
                    album=row.get('album')
                    samples.append({
                      'song':row.get('name') or row.get('title'),
                      'id':row.get('id'),
                      'artists':artist_names(row),
                      'year_fields':{k:row.get(k) for k in ('year','releaseYear','release_year','releaseDate','release_date','date') if row.get(k) is not None},
                      'parsed_year':year,
                      'album': {'name':album.get('name'), 'year':album.get('year'),'id':album.get('id')} if isinstance(album,dict) else str(album or ''),
                      'language':row.get('language'),
                      'genre':labels(row, ('genre','genres','tags','category','categories','type')),
                      'explicit_movie':row.get('movie') or row.get('film') or row.get('movieName') or row.get('filmName'),
                      'film_verified_by_current_code':movie,
                      'ghazal_verified_by_current_code':is_ghazal(row),
                      'artist_matched':matched,
                      'metadata_keys':sorted(row.keys())
                    })
            report['artists'][artist] = {'counts':dict(counts),'samples':samples}
            totals.update(counts)
            print(artist,dict(counts),flush=True)
        except Exception as e:
            report['artists'][artist]={'error':type(e).__name__+': '+str(e)[:150]}
            print(artist,'ERROR',type(e).__name__,flush=True)
    report['summary']=dict(totals)
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Diagnostic created:',output,'; device/firmware untouched',flush=True)

def v_enabled(x):
    return x.get('enabled') is True and isinstance(x.get('base_url'),str) and x['base_url'].startswith('https://')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--mode',default='hindi_classic_movie_1970_2010',choices=MODES)
    p.add_argument('--limit',type=int,default=40)
    p.add_argument('--output',default='dj_metadata_diagnostic.json')
    a=p.parse_args()
    run(a.mode,a.limit,a.output)
