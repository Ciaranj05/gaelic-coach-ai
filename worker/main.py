from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
import yt_dlp
import tempfile
import subprocess
import base64

app = FastAPI(title='Gaelic Coach AI Worker')

class AnalyseRequest(BaseModel):
    url: str
    notes: str | None = ''
    matchContext: dict | None = None

@app.get('/')
def health():
    return {'status': 'running', 'service': 'gaelic-coach-ai-worker'}

@app.get('/openai-status')
def openai_status():
    has_key = bool(os.getenv('OPENAI_API_KEY'))
    return {'connected': has_key, 'status': 'configured' if has_key else 'missing_key'}


def is_veo_url(url: str):
    return 'veo.co' in url.lower()


def processing_profile(url: str):
    if is_veo_url(url):
        return {
            'name': 'quick-veo',
            'video_format': 'best[height<=360]/best',
            'audio_format': 'worstaudio/bestaudio',
            'frame_interval': 180,
            'max_frames': 20,
            'scale': 512,
            'transcribe': False
        }
    return {
        'name': 'standard',
        'video_format': 'best[height<=480]/best',
        'audio_format': 'bestaudio/best',
        'frame_interval': 60,
        'max_frames': 60,
        'scale': 640,
        'transcribe': True
    }


def format_timestamp(seconds: float):
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def extract_video_metadata(url: str):
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'nocheckcertificate': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'uploader': info.get('uploader', ''),
                'duration': info.get('duration', 0),
                'filesize': info.get('filesize') or info.get('filesize_approx') or 0
            }
    except Exception:
        return {'title': '', 'description': '', 'uploader': '', 'duration': 0, 'filesize': 0}


def build_match_facts(match_context: dict):
    team_a = match_context.get('teamA', 'Team A')
    team_b = match_context.get('teamB', 'Team B')
    coached_team = match_context.get('coachedTeam', team_a)
    a_goals = int(match_context.get('teamAGoals') or 0)
    a_points = int(match_context.get('teamAPoints') or 0)
    b_goals = int(match_context.get('teamBGoals') or 0)
    b_points = int(match_context.get('teamBPoints') or 0)
    a_total = a_goals * 3 + a_points
    b_total = b_goals * 3 + b_points

    if a_total > b_total:
        winner, loser, margin = team_a, team_b, a_total - b_total
    elif b_total > a_total:
        winner, loser, margin = team_b, team_a, b_total - a_total
    else:
        winner, loser, margin = 'Draw', 'Draw', 0

    if margin == 0:
        result_type = 'draw'
    elif margin <= 3:
        result_type = 'narrow win'
    elif margin <= 8:
        result_type = 'competitive win'
    elif margin <= 14:
        result_type = 'strong win'
    else:
        result_type = 'dominant win'

    coached_result = 'drew' if winner == 'Draw' else ('won' if winner == coached_team else 'lost')
    return {
        'teamA': team_a,
        'teamB': team_b,
        'coachedTeam': coached_team,
        'teamAColour': match_context.get('teamAColour', ''),
        'teamBColour': match_context.get('teamBColour', ''),
        'competition': match_context.get('competition', ''),
        'teamAScore': f'{a_goals}-{a_points}',
        'teamBScore': f'{b_goals}-{b_points}',
        'teamATotal': a_total,
        'teamBTotal': b_total,
        'winner': winner,
        'loser': loser,
        'margin': margin,
        'resultType': result_type,
        'coachedTeamResult': coached_result,
        'scoreline': f'{team_a} {a_goals}-{a_points} ({a_total}) vs {team_b} {b_goals}-{b_points} ({b_total})'
    }


def transcribe_audio(url: str, client: OpenAI, profile: dict):
    if not profile['transcribe']:
        return {'text': '', 'segments': 'Transcript skipped in quick Veo mode to reduce processing time.'}
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, 'audio.%(ext)s')
            ydl_opts = {
                'format': profile['audio_format'],
                'outtmpl': output_template,
                'quiet': True,
                'noplaylist': True,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '48'}]
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            audio_path = os.path.join(tmpdir, 'audio.mp3')
            if not os.path.exists(audio_path):
                return {'text': '', 'segments': ''}
            with open(audio_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(model='whisper-1', file=audio_file, response_format='verbose_json')
            text = getattr(transcript, 'text', '') or ''
            raw_segments = getattr(transcript, 'segments', None) or []
            segments = []
            for segment in raw_segments[:80]:
                start = segment.get('start') if isinstance(segment, dict) else getattr(segment, 'start', 0)
                segment_text = segment.get('text') if isinstance(segment, dict) else getattr(segment, 'text', '')
                if segment_text:
                    segments.append(f'{format_timestamp(start)} - {segment_text.strip()}')
            return {'text': text, 'segments': '\n'.join(segments)}
    except Exception:
        return {'text': '', 'segments': ''}


def extract_frames(url: str, client: OpenAI, profile: dict):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, 'match.mp4')
            frame_pattern = os.path.join(tmpdir, 'frame_%03d.jpg')
            ydl_opts = {
                'format': profile['video_format'],
                'outtmpl': video_path,
                'quiet': False,
                'noplaylist': True,
                'merge_output_format': 'mp4',
                'nocheckcertificate': True,
                'socket_timeout': 30,
                'retries': 2,
                'fragment_retries': 2
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            if not os.path.exists(video_path):
                return {'observations': '', 'moments': ''}

            interval = profile['frame_interval']
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path,
                '-vf', f'fps=1/{interval},scale={profile["scale"]}:-1',
                '-frames:v', str(profile['max_frames']), frame_pattern
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            frame_paths = sorted([
                os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
                if f.startswith('frame_') and f.endswith('.jpg')
            ])[:profile['max_frames']]
            if not frame_paths:
                return {'observations': '', 'moments': ''}

            observations = []
            moments = []
            for batch_index in range(0, len(frame_paths), 10):
                frame_batch = frame_paths[batch_index:batch_index + 10]
                start_seconds = batch_index * interval
                end_seconds = start_seconds + (len(frame_batch) - 1) * interval
                batch_window = f'{format_timestamp(start_seconds)} to {format_timestamp(end_seconds)}'
                content = [{
                    'type': 'text',
                    'text': f'Review sampled Gaelic games frames from approximately {batch_window}. Images are about {interval} seconds apart. Describe only visible tactical evidence: spacing, density, width, compactness, restarts, transition spacing and pressure. Return 3-5 timestamped moments. Do not infer scores, winner, draw, equalisers, player names or exact scoring events. State uncertainty when evidence is weak.'
                }]
                for offset, frame_path in enumerate(frame_batch):
                    content.append({'type': 'text', 'text': f'Frame approximate timestamp: {format_timestamp(start_seconds + offset * interval)}'})
                    with open(frame_path, 'rb') as image_file:
                        encoded = base64.b64encode(image_file.read()).decode('utf-8')
                    content.append({'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{encoded}', 'detail': 'low'}})
                response = client.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'user', 'content': content}])
                text = response.choices[0].message.content or ''
                observations.append(f'FRAME BATCH ({batch_window})\n{text}')
                moments.append(text)
            return {'observations': '\n\n'.join(observations), 'moments': '\n\n'.join(moments)}
    except Exception:
        return {'observations': '', 'moments': ''}


@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)
    profile = processing_profile(request.url)
    metadata = extract_video_metadata(request.url)
    transcript_data = transcribe_audio(request.url, client, profile)
    frame_data = extract_frames(request.url, client, profile)

    transcript = transcript_data['text']
    timestamped_transcript = transcript_data['segments']
    visual_observations = frame_data['observations']
    timestamped_frame_moments = frame_data['moments']

    match_context = request.matchContext or {}
    match_facts = build_match_facts(match_context)
    coached_team = match_facts['coachedTeam']
    opposition_team = match_facts['teamB'] if match_facts['teamA'] == coached_team else match_facts['teamA']

    prompt = f'''
You are a senior Gaelic games performance analyst. Produce evidence-based tactical analysis only.

Hard match facts: {match_facts}
Processing profile: {profile['name']}.
Rules: do not contradict the scoreline, winner, margin or coached-team result. Do not invent a draw, equaliser, exact score event or player identity. Use actual team names. Analyse from {coached_team}'s perspective. If the evidence is weak, say so. If quick Veo mode was used, state that analysis used lower-resolution sampled frames and limited/no transcript.

Video: {metadata}
Timestamped transcript: {timestamped_transcript[:10000]}
Transcript: {transcript[:6000]}
Timestamped frame moments: {timestamped_frame_moments[:10000]}
Visual observations: {visual_observations[:8000]}
Coach notes: {request.notes}

Return these clean sections:
# Result Snapshot
# Why {coached_team} {match_facts['coachedTeamResult']}
# Key Timestamped Moments
# Strengths Shown By {coached_team}
# Weaknesses / Risks For {coached_team}
# What Hurt {opposition_team}
# Tactical Themes Worth Reviewing
# Training Priorities
# Confidence Notes

For timestamped moments, include approximate timestamp, observation, impact and coaching note. Keep it concise and premium.
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'You are an elite Gaelic games tactical analyst. Obey hard scoreline facts and produce evidence-first coaching intelligence.'},
            {'role': 'user', 'content': prompt}
        ]
    )

    analysis = response.choices[0].message.content
    return {
        'status': 'complete',
        'mode': 'worker',
        'analysis': analysis,
        'videoMetadata': metadata,
        'matchFacts': match_facts,
        'processingProfile': profile['name'],
        'transcriptLength': len(transcript),
        'timestampedTranscriptLength': len(timestamped_transcript),
        'visualAnalysisLength': len(visual_observations),
        'timestampedFrameMomentsLength': len(timestamped_frame_moments),
        'framesSampledTarget': profile['max_frames'],
        'next_stage': 'Future upgrade: background jobs, real-time progress polling and clip generation.'
    }
