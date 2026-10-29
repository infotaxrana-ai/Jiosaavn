#!/usr/bin/env python3
"""Xiaozhi DJ Step 4: read-only API/firmware compatibility audit.
No device commands, no media streaming, no repository publishing.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent

def audit(config_path='music_config.json', preview_path='dj_mode_preview.json', output_path='dj_integration_audit.json'):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    preview = json.loads(Path(preview_path).read_text(encoding='utf-8'))
    songs = preview.get('songs', [])
    valid = []
    invalid = []
    for song in songs:
        u = song.get('audio_url', '')
        p = urlsplit(u) if isinstance(u, str) else None
        if (isinstance(song.get('title'), str) and song['title'].strip() and
                isinstance(song.get('artist'), str) and song['artist'].strip() and
                p and p.scheme == 'https' and p.hostname):
            valid.append(song)
        else:
            invalid.append(song.get('id'))
    issues = []
    if not preview.get('preview_only'):
        issues.append('Playlist is not marked preview_only: inspect it manually')
    if not songs:
        issues.append('No DJ candidates selected; check provider access and restrictive metadata rules')
    if invalid:
        issues.append(f'{len(invalid)} candidates have invalid title/artist/audio URL')
    # The supplied repository contains API configuration and playlist candidates,
    # but no verified device-side external playlist ingestion contract.
    issues.append('No verified current ESP32 MCP tool or firmware route accepts an external DJ playlist/URL')
    report = {
        'step': 4, 'mode': preview.get('mode'),
        'music_config_revision': config.get('config_revision'),
        'candidate_count': len(songs),
        'metadata_valid_count': len(valid),
        'source_audits': preview.get('source_audits', {}),
        'unavailable_artists': preview.get('unavailable_artists', []),
        'firmware_modified': False,
        'device_playback_tested': False,
        'device_queue_integration': 'NOT VERIFIED',
        'deployment_status': 'BLOCKED_PENDING_DEVICE_INTERFACE_VERIFICATION',
        'issues': issues,
        'required_device_evidence': [
            'Current MCP registered tool name/schema that accepts queue or direct audio URLs',
            'Current esp32_music.cc radio queue search/load path and supported JSON/URL contract',
            'A device-side log proving a playlist is accepted and queued'
        ]
    }
    Path(output_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('DJ STEP 4 READ-ONLY AUDIT')
    print('Mode:', report['mode'], '| candidates:', len(songs), '| valid:', len(valid))
    print('Integration:', report['deployment_status'])
    print('Firmware, Music MCP, News, Alarm: UNTOUCHED')
    return report

if __name__ == '__main__':
    audit()
