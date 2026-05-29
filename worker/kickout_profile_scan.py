import os
import tempfile
from typing import Any

from openai import OpenAI

from kickout_reference import (
    DEFAULT_BUCKET,
    POSITIVE_PREFIX,
    NEGATIVE_PREFIX,
    _image_content_from_path,
    compare_frame_paths_to_reference,
    download_reference_images,
    download_video,
    extract_video_frame_from_file,
    get_video_duration_seconds,
    kickout_decision,
    list_reference_images,
)


DEFAULT_KICKOUT_PROFILE = '''
Gaelic football kickout visual profile:
YES / likely kickout when the frame shows a restart setup with a goalkeeper or restart player deep near the goal area, the ball appears static or restart-like, players are spread into short/wide/long receiving lanes, immediate pressure is low, and the shape looks structured from defensive third into middle third.
NO / not a kickout when the frame shows open play, active tackling/contact, clustered contests around the ball, sideline congestion, attacking-third action, running transition, the ball already moving in play, or no clear restart structure.
Use a conservative manager-facing decision. Return YES only for clear restart setups, REVIEW for plausible but uncertain kickout shapes, and NO for open play.
'''.strip()


def build_kickout_profile_from_library(bucket_name: str = DEFAULT_BUCKET) -> dict[str, Any]:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is missing')

    positive_names = list_reference_images(bucket_name, POSITIVE_PREFIX, limit=10)
    negative_names = list_reference_images(bucket_name, NEGATIVE_PREFIX, limit=10)
    if not positive_names or not negative_names:
        raise RuntimeError('Kickout reference library is missing positive or negative images')

    with tempfile.TemporaryDirectory() as tmpdir:
        positive_paths = download_reference_images(bucket_name, positive_names, os.path.join(tmpdir, 'positive'))
        negative_paths = download_reference_images(bucket_name, negative_names, os.path.join(tmpdir, 'negative'))
        content: list[dict[str, Any]] = [
            {
                'type': 'text',
                'text': '''Create a compact reusable Gaelic football kickout visual profile from these labelled examples.
Positive images are confirmed kickout setups. Negative images are confirmed non-kickouts/open play.
Return JSON only with keys: profile, yesRules, noRules, reviewRules.
The profile must be short enough to reuse when scanning many match frames.'''
            },
            {'type': 'text', 'text': 'POSITIVE KICKOUT EXAMPLES:'},
        ]
        content.extend(_image_content_from_path(path) for path in positive_paths)
        content.append({'type': 'text', 'text': 'NEGATIVE NON-KICKOUT EXAMPLES:'})
        content.extend(_image_content_from_path(path) for path in negative_paths)

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            response_format={'type': 'json_object'},
            messages=[{'role': 'user', 'content': content}],
        )
        raw = response.choices[0].message.content or '{}'

    try:
        import json
        parsed = json.loads(raw)
    except Exception:
        parsed = {'profile': DEFAULT_KICKOUT_PROFILE, 'raw': raw}

    profile = str(parsed.get('profile') or DEFAULT_KICKOUT_PROFILE)
    return {
        'profile': profile,
        'yesRules': parsed.get('yesRules', []),
        'noRules': parsed.get('noRules', []),
        'reviewRules': parsed.get('reviewRules', []),
        'referenceLibrary': {
            'bucket': bucket_name,
            'positivePrefix': POSITIVE_PREFIX,
            'negativePrefix': NEGATIVE_PREFIX,
            'positiveCount': len(positive_names),
            'negativeCount': len(negative_names),
        }
    }


def classify_frame_with_profile(client: OpenAI, frame_path: str, profile: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            'type': 'text',
            'text': f'''Classify this Gaelic football frame using the reusable kickout visual profile below.

{profile}

Return JSON only with keys:
- decision: YES|REVIEW|NO
- isKickout: boolean
- managerLabel: Kickout identified|Possible kickout — review|Not a kickout
- confidence: low|medium|high
- reasoning: short reason

Decision rules:
YES only when it is clearly a kickout/restart setup.
REVIEW when it could be a kickout but visual evidence is uncertain.
NO when it is open play, transition, tackling, clustered contest, or not a restart.'''
        },
        {'type': 'text', 'text': 'CANDIDATE FRAME:'},
        _image_content_from_path(frame_path),
    ]
    response = client.chat.completions.create(
        model='gpt-4o-mini',
        response_format={'type': 'json_object'},
        messages=[{'role': 'user', 'content': content}],
    )
    raw = response.choices[0].message.content or '{}'
    try:
        import json
        parsed = json.loads(raw)
    except Exception:
        parsed = {'decision': 'REVIEW', 'isKickout': False, 'managerLabel': 'Possible kickout — review', 'confidence': 'low', 'reasoning': raw}

    decision = str(parsed.get('decision') or 'NO').upper()
    if decision not in ['YES', 'REVIEW', 'NO']:
        decision = 'NO'
    is_kickout = decision == 'YES'
    manager_label = parsed.get('managerLabel')
    if not manager_label:
        manager_label = 'Kickout identified' if decision == 'YES' else ('Possible kickout — review' if decision == 'REVIEW' else 'Not a kickout')
    parsed.update({'decision': decision, 'isKickout': is_kickout, 'managerLabel': manager_label})
    return parsed


def scan_match_for_kickouts_with_profile(
    video_url: str,
    bucket_name: str = DEFAULT_BUCKET,
    interval_seconds: int = 30,
    max_frames: int = 200,
    include_review: bool = True,
) -> dict[str, Any]:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is missing')

    interval_seconds = max(15, int(interval_seconds or 30))
    max_frames = max(1, min(500, int(max_frames or 200)))
    profile_payload = build_kickout_profile_from_library(bucket_name)
    profile = profile_payload['profile']

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, 'match.mp4')
        download_video(video_url, video_path)
        duration = get_video_duration_seconds(video_path)
        if duration <= 0:
            raise RuntimeError('Unable to read video duration for kickout profile scan')

        client = OpenAI(api_key=api_key)
        timestamps = list(range(0, duration, interval_seconds))[:max_frames]
        results: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []

        for index, timestamp in enumerate(timestamps, start=1):
            frame_path = extract_video_frame_from_file(video_path, timestamp, tmpdir, f'profile_candidate_{index:03d}')
            parsed = classify_frame_with_profile(client, frame_path, profile)
            row = {
                'timestamp': timestamp,
                'time': f'{timestamp//60:02d}:{timestamp%60:02d}',
                'isKickout': bool(parsed.get('isKickout')),
                'decision': parsed.get('decision', 'NO'),
                'managerLabel': parsed.get('managerLabel', 'Not a kickout'),
                'confidence': parsed.get('confidence', 'low'),
                'reasoning': parsed.get('reasoning', ''),
            }
            results.append(row)
            if row['decision'] == 'YES' or (include_review and row['decision'] == 'REVIEW'):
                candidates.append(row)

    return {
        'ok': True,
        'test': 'kickout-profile-full-match-scan',
        'durationSeconds': duration,
        'intervalSeconds': interval_seconds,
        'framesTested': len(results),
        'candidateCount': len(candidates),
        'candidates': candidates,
        'allResults': results,
        'profile': profile_payload,
    }
