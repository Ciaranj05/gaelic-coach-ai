import os
import tempfile
from typing import Any

from openai import OpenAI

from kickout_reference import (
    DEFAULT_BUCKET,
    POSITIVE_PREFIX,
    NEGATIVE_PREFIX,
    _image_content_from_path,
    download_reference_images,
    download_video,
    extract_video_frame_from_file,
    get_video_duration_seconds,
    list_reference_images,
)


DEFAULT_KICKOUT_PROFILE = '''
Gaelic football kickout visual profile — STRICT MODE:
A confirmed kickout is a dead-ball restart from the goalkeeper/defensive goal area after a score or wide. Do not call ordinary structured possession a kickout.

YES / Kickout identified only when most of these are visible:
- Goalkeeper or restart taker is clearly deep in/near the defensive goal area.
- Ball appears stationary or restart-like, not already live in open play.
- Players are waiting/set rather than actively running, tackling, contesting, or transitioning.
- Receiving team is spread into deliberate short, wide, middle, or long kickout lanes.
- Immediate pressure is low or organised as a press rather than a live tackle/contest.
- The frame clearly looks like a restart moment, not just a structured attacking or defensive shape.

REVIEW only when the frame has a plausible restart shape but one key cue is missing, such as unclear ball status or unclear goalkeeper/restart taker.

NO / Not a kickout when:
- It only shows players in a structured formation or spaced shape.
- The ball is live, players are running, tackling, contesting, or transitioning.
- The camera shows midfield/open play with no defensive goal-area restart context.
- There is sideline play, attacking-third play, a free, a mark, or general possession shape.
- The goalkeeper/restart taker and dead-ball setup are not visible.

Be conservative. False positives are worse than missing borderline cases. Return YES only for clear kickouts.
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

STRICT requirements:
- YES must require dead-ball restart context, preferably goalkeeper/restart taker near defensive goal area.
- Do NOT use generic structured formation, spacing, or players in zones as enough for YES.
- General open play, live possession, running, tackling, transition, sideline play, free/mark, or attacking shape must be NO.
- REVIEW is only for plausible restart frames missing one key cue.
- False positives are worse than missed borderline cases.
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

    learned_profile = str(parsed.get('profile') or '').strip()
    profile = DEFAULT_KICKOUT_PROFILE
    if learned_profile:
        profile = f'{DEFAULT_KICKOUT_PROFILE}\n\nReference-library notes:\n{learned_profile}'

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
            'text': f'''Classify this Gaelic football frame using the STRICT kickout visual profile below.

{profile}

Return JSON only with keys:
- decision: YES|REVIEW|NO
- isKickout: boolean
- managerLabel: Kickout identified|Possible kickout — review|Not a kickout
- confidence: low|medium|high
- reasoning: short reason

STRICT decision rules:
YES = only a clear dead-ball kickout/restart, ideally with goalkeeper/restart taker near defensive goal area, ball static/restart-like, and players waiting/set in kickout lanes.
REVIEW = plausible restart but missing one important cue.
NO = open play, live ball, transition, tackling, clustered contest, sideline/free/mark, attacking shape, midfield shape, or only generic structured spacing.
Do not say YES just because players are organised, spread, or in zones.
If unsure between YES and REVIEW, choose REVIEW.
If unsure between REVIEW and NO, choose NO.
False positives are worse than missing borderline kickouts.'''
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
        parsed = {'decision': 'NO', 'isKickout': False, 'managerLabel': 'Not a kickout', 'confidence': 'low', 'reasoning': raw}

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
    include_review: bool = False,
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
        'test': 'kickout-profile-full-match-scan-strict',
        'durationSeconds': duration,
        'intervalSeconds': interval_seconds,
        'framesTested': len(results),
        'candidateCount': len(candidates),
        'candidates': candidates,
        'allResults': results,
        'profile': profile_payload,
    }
