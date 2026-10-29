#!/usr/bin/env python3
"""Audit-first, deny-by-default playlist release gate. Stdlib only. No firmware writes."""
import argparse, csv, hashlib, html, json, re, urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

MAX_YEAR_MIN, MAX_YEAR_MAX = 1970, 2010
BAD_HINTS = re.compile(r'\b(remix|karaoke|instrumental|cover|tribute|jhankar|aarti|bhajan)\b',re.I)

def normalize(text):
    text=html.unescape(str(text or '')).casefold()
    return ' '.join(re.sub(r'[^a-z0-9]+',' ',text).split())

def inventory(data):
    raw=data.get('unverified_film_candidates',[])
    if not isinstance(raw,list):raise ValueError('bad candidate array')
    groups={}
    for item in raw:
        if not isinstance(item,dict): continue
        sid=str(item.get('id','')).strip()
        if not sid or not str(item.get('title','')).strip() or not str(item.get('album','')).strip():continue
        if not str(item.get('audio_url','')).startswith('https://'):continue
        if sid not in groups:
            groups[sid]={**item,'source_artist_labels':[item.get('artist','')]}
        else:
            if normalize(item.get('title')) != normalize(groups[sid].get('title')) or normalize(item.get('album')) != normalize(groups[sid].get('album')):
                groups[sid]['conflicting_id_metadata']=True
            label=item.get('artist','')
            if label not in groups[sid]['source_artist_labels']:groups[sid]['source_artist_labels'].append(label)
    return groups

def valid_evidence(entry):
    """Two separately hosted evidence URLs, with explicit human verification confirmations."""
    urls=entry.get('evidence_urls',[])
    if not isinstance(urls,list) or len(urls)<2: return False,'requires_two_evidence_urls'
    hosts=set()
    for url in urls:
        try:
            p=urllib.parse.urlparse(url)
            if p.scheme!='https' or not p.hostname or '.' not in p.hostname or p.username or p.password:return False,'invalid_evidence_url'
            hosts.add(p.hostname.lower().removeprefix('www.'))
        except (TypeError,ValueError,AttributeError):return False,'invalid_evidence_url'
    if len(hosts)<2:return False,'requires_independent_domains'
    checks=entry.get('confirmed',{})
    required=('song_to_film','original_film_year','hindi_language','singer_credits','recording_identity','licensing_rights')
    if not isinstance(checks,dict) or any(checks.get(f) is not True for f in required):return False,'missing_verified_claims'
    return True,''

def run(source,review,require_device=True):
    items=inventory(source)
    approved=[];pending=[];rejected=[];stats=Counter();seen_rec=set()
    if not isinstance(review,dict):raise ValueError('review must be a JSON object keyed by song ID')
    for sid,item in items.items():
        row=review.get(sid)
        if row is None:
            pending.append({'id':sid,'title':item['title'],'album':item['album'],'reason':'not_reviewed'})
            stats['not_reviewed']+=1;continue
        if row.get('decision')=='reject':
            rejected.append({'id':sid,'title':item['title'],'reason':row.get('reason','reviewer_rejected')})
            stats['rejected']+=1;continue
        if row.get('decision')!='approve':
            pending.append({'id':sid,'title':item['title'],'reason':'no_explicit_approval'})
            stats['pending']+=1;continue
        year=row.get('original_film_year')
        if not isinstance(year,int) or isinstance(year,bool) or not MAX_YEAR_MIN<=year<=MAX_YEAR_MAX:
            pending.append({'id':sid,'title':item['title'],'reason':'invalid_original_film_year'})
            stats['invalid_year']+=1;continue
        album=row.get('film_title','')
        if normalize(album)!=normalize(item['album']):
            # Remasters and soundtrack editions should be manually handled with a separate mapping
            pending.append({'id':sid,'title':item['title'],'reason':'film_album_mismatch'})
            stats['film_album_mismatch']+=1;continue
        if item.get('conflicting_id_metadata'):
            pending.append({'id':sid,'title':item['title'],'reason':'conflicting_source_id'})
            stats['conflicting_id']+=1;continue
        if BAD_HINTS.search(item['title']) or BAD_HINTS.search(item['album']):
            pending.append({'id':sid,'title':item['title'],'reason':'non_original_recording_hint'})
            stats['recording_hint']+=1;continue
        good,reason=valid_evidence(row)
        if not good:
            pending.append({'id':sid,'title':item['title'],'reason':reason})
            stats[reason]+=1;continue
        if require_device and row.get('device_playback_test') is not True:
            pending.append({'id':sid,'title':item['title'],'reason':'device_playback_not_confirmed'})
            stats['device_pending']+=1;continue
        rid=normalize(row.get('recording_canonical_id') or sid)
        if rid in seen_rec:
            stats['duplicate_recording']+=1;continue
        seen_rec.add(rid)
        approved.append({'id':sid,'title':item['title'],'artist':row.get('verified_artist_credits',item['artist']),
                         'film':album,'original_film_year':year,'audio_url':item['audio_url'],
                         'verification_evidence_urls':row['evidence_urls'],
                         'device_tested':True if require_device else bool(row.get('device_playback_test'))})
        stats['approved']+=1
    status='READY' if approved and not require_device or approved and require_device else 'BLOCKED_NO_APPROVED_TRACKS'
    return {'schema_version':3,'preview_only':True,'status':status,'metadata_tracks':approved if not require_device else [],
            'device_verified_tracks':approved if require_device else [],'pending':pending,'rejected':rejected,
            'stats':{'input_rows':len(source.get('unverified_film_candidates',[])), 'unique_ids':len(items),**dict(stats)},
            'guarantees':['No entry accepted without reviewed explicit evidence and required checks'],
            'caveats':['Approval fields are reviewer attestations, not automatic proof.',
                       'Audio and license status require separate direct verification.',
                       'No run can guarantee absolute correctness of changing remote data.']}

def write_review_csv(items,path):
    with open(path,'w',newline='',encoding='utf-8-sig') as fp:
        w=csv.writer(fp);w.writerow(['id','title','source_artist_labels','album','api_release_year','audio_url','review_decision','original_film_year','film_title','source_1','source_2','notes'])
        for sid,item in items.items():
            w.writerow([sid,item['title'],' / '.join(item['source_artist_labels']),item['album'],item.get('release_year_not_film_year',''),item['audio_url'],'','','','','',''])

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='data/recovery_snapshot.json')
    p.add_argument('--review',default='data/verified_reviews.json');p.add_argument('--output',default='precision_report.json')
    p.add_argument('--csv',default='review_all_candidates.csv');p.add_argument('--metadata-only',action='store_true');a=p.parse_args()
    source=json.loads(Path(a.input).read_text(encoding='utf-8'))
    review=json.loads(Path(a.review).read_text(encoding='utf-8'))
    result=run(source,review,not a.metadata_only)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_review_csv(inventory(source),a.csv)
    print('PRECISION RELEASE:',json.dumps(result['stats']),flush=True)
    print('STATUS:',result['status'],'| DEVICE INTEGRATION UNTOUCHED',flush=True)
    if result['status']!='READY':raise SystemExit('RELEASE BLOCKED: no independently reviewed device-tested tracks.')
if __name__=='__main__':main()
