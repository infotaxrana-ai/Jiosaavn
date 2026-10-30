
#!/usr/bin/env python3
"""Xiaozhi Step 2: read-only JioSaavn artist search audit / DJ candidate filter.
Prefer genuine 48 kbps audio URLs.
No firmware changes. No automatic publishing or playback.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = 'https://elitejiosaavn-api.vercel.app'

ALIASES = {
    'kumar sanu': {'kumar sanu', 'kumar shanu', 'কুমার শানু', 'শানু'},
    'pankaj udhas': {'pankaj udhas', 'pankaj udhas ji', 'পঙ্কজ উদাস'},
    'udit narayan': {'udit narayan', 'উদিত নারায়ণ', 'উদিত নারায়ণ'},
    'arijit singh': {'arijit singh', 'arijit', 'অরিজিৎ সিং', 'অরিজিত'},
    'runa laila': {'runa laila', 'রুনা লায়লা', 'রুনা লাইলা'},
    'kanak chapa': {'kanak chapa', 'kanak champa', 'কনকচাঁপা', 'কনক চাপা'},
}

def norm(s):
    s = unicodedata.normalize('NFKC', str(s or '')).casefold()
    s = re.sub(r'[^\w\u0980-\u09ff]+', ' ', s, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', s).strip()

def aliases_for(name):
    key = norm(name)
    for canon, choices in ALIASES.items():
        if key in {norm(x) for x in choices}:
            return {norm(x) for x in choices} | {norm(canon)}
    return {key}

def match_artist(candidate, target):
    if not candidate or not target:
        return False
    c = norm(candidate)
    return any(c == alt for alt in aliases_for(target))

def artist_names(song):
    result = []
    arts = song.get('artists') or {}

    if isinstance(arts, dict):
        for key in ('primary', 'featured', 'all'):
            for item in arts.get(key) or []:
                if isinstance(item, dict):
                    result.append(item.get('name') or '')
                elif isinstance(item, str):
                    result.append(item)

    elif isinstance(arts, list):
        result.extend(
            x.get('name', '') if isinstance(x, dict) else str(x)
            for x in arts
        )

    for key in ('primaryArtists', 'primary_artists', 'singers'):
        x = song.get(key)
        if isinstance(x, str):
            result.extend(re.split(r'[,;/|]+', x))

    return list(dict.fromkeys(
        x.strip() for x in result if x and x.strip()
    ))


# ==================================================
# XIAOZHI DJ - 48 KBPS AUDIO URL SELECTION
# ==================================================

def audio_url(song):
    items = song.get('downloadUrl') or song.get('download_url') or []

    if isinstance(items, str):
        items = [{'url': items, 'quality': 'unknown'}]

    if not isinstance(items, list):
        return None

    for item in items:

        if isinstance(item, dict):
            url = item.get('url') or item.get('link')
            quality = str(item.get('quality', '')).lower().strip()

        elif isinstance(item, str):
            url = item
            quality = ''

        else:
            continue

        if not isinstance(url, str):
            continue

        parsed = urllib.parse.urlparse(url)

        if parsed.scheme != 'https' or not parsed.hostname:
            continue

        # Genuine 48 kbps quality from API metadata
        if quality in ('48kbps', '48 kbps', '48'):
            return url

        # Recognize an existing 48 kbps CDN URL
        if re.search(r'_48\.(mp4|m4a)(?:$|\?)', url, re.I):
            return url

    # Never invent _48 URLs by replacing _320.
    # Never silently fall back to 320 kbps.
    return None


def get_results(payload):
    if isinstance(payload, list):
        return payload

    d = payload.get('data', {})

    if isinstance(d, list):
        return d

    if not isinstance(d, dict):
        return []

    if isinstance(d.get('results'), list):
        return d['results']

    songs = d.get('songs')

    if isinstance(songs, dict) and isinstance(songs.get('results'), list):
        return songs['results']

    return []


def filter_songs(payload, artist, max_items=30):
    accepted = []
    counts = dict(
        total=0,
        artist_mismatch=0,
        no_artist=0,
        no_audio=0,
        duplicate=0,
        invalid=0
    )

    seen = set()

    for song in get_results(payload):
        counts['total'] += 1

        if not isinstance(song, dict):
            counts['invalid'] += 1
            continue

        names = artist_names(song)

        if not names:
            counts['no_artist'] += 1
            continue

        if not any(match_artist(x, artist) for x in names):
            counts['artist_mismatch'] += 1
            continue

        title = song.get('name') or song.get('title') or ''

        # Select the API-provided 48 kbps URL
        url = audio_url(song)

        if not title or not url:
            counts['no_audio'] += 1
            continue

        identity = (norm(title), norm(artist))

        if identity in seen:
            counts['duplicate'] += 1
            continue

        seen.add(identity)

        accepted.append(dict(
            id=song.get('id'),
            title=title,
            artist=artist,
            actual_artists=names,
            audio_url=url
        ))

        if len(accepted) >= max_items:
            break

    return {
        'artist': artist,
        'songs': accepted,
        'counts': counts,
        'warning': (
            'Review-only 48 kbps candidates; '
            'do not assume ESP32 can load this list.'
        )
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--artist', required=True)
    ap.add_argument('--fixture', help='Local JSON response; no network')
    ap.add_argument('--base-url', default=DEFAULT_BASE)
    ap.add_argument('--limit', type=int, default=30)
    ap.add_argument('--output', default='dj_preview.json')

    args = ap.parse_args()

    if args.fixture:
        payload = json.loads(
            Path(args.fixture).read_text(encoding='utf-8')
        )

    else:
        parsed = urllib.parse.urlparse(args.base_url)

        if parsed.scheme != 'https' or not parsed.hostname:
            raise SystemExit('HTTPS base URL required')

        url = (
            args.base_url.rstrip('/')
            + '/api/search/songs?'
            + urllib.parse.urlencode({
                'query': args.artist,
                'limit': args.limit
            })
        )

        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'XiaozhiDJStep2/1.0',
                'Accept': 'application/json'
            }
        )

        with urllib.request.urlopen(req, timeout=15) as response:
            if urllib.parse.urlparse(response.geturl()).scheme != 'https':
                raise ValueError('insecure redirect')

            payload = json.loads(
                response.read(3_000_000).decode('utf-8')
            )

    result = filter_songs(
        payload,
        args.artist,
        args.limit
    )

    Path(args.output).write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        ) + '\n',
        encoding='utf-8'
    )

    print(
        'STEP 2 FILTER COMPLETE:',
        json.dumps(result['counts'], ensure_ascii=False)
    )

    print(
        'Accepted:',
        len(result['songs']),
        '| output:',
        args.output
    )

    print(
        'Audio quality preference: 48 kbps ONLY'
    )

    print(
        'No changes to Firmware, MCP, API config, '
        'or published playlist'
    )


if __name__ == '__main__':
    main()
