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
    return {
        'status': 'running',
        'service': 'gaelic-coach-ai-worker'
    }

@app.get('/openai-status')
def openai_status():
    has_key = bool(os.getenv('OPENAI_API_KEY'))
    return {
        'connected': has_key,
        'status': 'configured' if has_key else 'missing_key'
    }


def extract_video_metadata(url: str):
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'nocheckcertificate': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            return {
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'uploader': info.get('uploader', ''),
                'duration': info.get('duration', 0)
            }
    except Exception:
        return {
            'title': '',
            'description': '',
            'uploader': '',
            'duration': 0
        }


def build_match_facts(match_context: dict):
    team_a = match_context.get('teamA', 'Team A')
    team_b = match_context.get('teamB', 'Team B')
    coached_team = match_context.get('coachedTeam', team_a)

    a_goals = int(match_context.get('teamAGoals') or 0)
    a_points = int(match_context.get('teamAPoints') or 0)
    b_goals = int(match_context.get('teamBGoals') or 0)
    b_points = int(match_context.get('teamBPoints') or 0)

    a_total = (a_goals * 3) + a_points
    b_total = (b_goals * 3) + b_points

    if a_total > b_total:
        winner = team_a
        loser = team_b
        margin = a_total - b_total
    elif b_total > a_total:
        winner = team_b
        loser = team_a
        margin = b_total - a_total
    else:
        winner = 'Draw'
        loser = 'Draw'
        margin = 0

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

    if winner == 'Draw':
        coached_result = 'drew'
    elif winner == coached_team:
        coached_result = 'won'
    else:
        coached_result = 'lost'

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


def transcribe_audio_from_youtube(url: str, client: OpenAI):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, 'audio.%(ext)s')

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'quiet': True,
                'noplaylist': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64'
                }]
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            audio_path = os.path.join(tmpdir, 'audio.mp3')

            if not os.path.exists(audio_path):
                return ''

            with open(audio_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model='whisper-1',
                    file=audio_file
                )

            return transcript.text

    except Exception:
        return ''


def extract_frames_from_youtube(url: str, client: OpenAI):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, 'match.mp4')
            frame_pattern = os.path.join(tmpdir, 'frame_%03d.jpg')

            ydl_opts = {
                'format': 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                'outtmpl': video_path,
                'quiet': True,
                'noplaylist': True,
                'merge_output_format': 'mp4'
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if not os.path.exists(video_path):
                return ''

            subprocess.run(
                [
                    'ffmpeg', '-y', '-i', video_path,
                    '-vf', 'fps=1/60,scale=640:-1',
                    '-frames:v', '60',
                    frame_pattern
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )

            frame_paths = sorted([
                os.path.join(tmpdir, filename)
                for filename in os.listdir(tmpdir)
                if filename.startswith('frame_') and filename.endswith('.jpg')
            ])[:60]

            if not frame_paths:
                return ''

            frame_batches = [frame_paths[i:i + 10] for i in range(0, len(frame_paths), 10)]
            observations = []

            for batch_number, frame_batch in enumerate(frame_batches, start=1):
                content = [
                    {
                        'type': 'text',
                        'text': 'Review these sampled Gaelic games frames. Only describe visible tactical evidence: spacing, player density, attacking width, defensive compactness, kickout/restart shape, transition spacing and pressure. Do not infer the score, winner, equaliser, draw, player names or exact events from frames. State uncertainty where evidence is weak.'
                    }
                ]

                for frame_path in frame_batch:
                    with open(frame_path, 'rb') as image_file:
                        encoded = base64.b64encode(image_file.read()).decode('utf-8')
                        content.append({
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/jpeg;base64,{encoded}',
                                'detail': 'low'
                            }
                        })

                response = client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[{'role': 'user', 'content': content}]
                )

                observations.append(response.choices[0].message.content or '')

            return '\n\n'.join(observations)

    except Exception:
        return ''


@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    api_key = os.getenv('OPENAI_API_KEY')

    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)

    metadata = extract_video_metadata(request.url)
    transcript = transcribe_audio_from_youtube(request.url, client)
    visual_observations = extract_frames_from_youtube(request.url, client)

    match_context = request.matchContext or {}
    match_facts = build_match_facts(match_context)
    coached_team = match_facts['coachedTeam']
    opposition_team = match_facts['teamB'] if match_facts['teamA'] == coached_team else match_facts['teamA']

    result_guardrail = f"""
HARD MATCH FACTS - DO NOT CONTRADICT THESE:
- Scoreline: {match_facts['scoreline']}
- Winner: {match_facts['winner']}
- Losing team: {match_facts['loser']}
- Margin: {match_facts['margin']} points
- Result type: {match_facts['resultType']}
- Coached team: {coached_team}
- Coached team result: {match_facts['coachedTeamResult']}

STRICT RESULT RULES:
- If margin is greater than 0, NEVER describe the match as a draw.
- If margin is 9 or more, NEVER describe the game as level, equalised, or close unless the user explicitly provides a timestamped note proving a temporary in-game equaliser.
- If {coached_team} won, explain why {coached_team} won. Do not say they failed to control the match overall.
- If {coached_team} lost, explain why {coached_team} lost.
- Do not say {opposition_team} equalised unless there is explicit transcript or coach-note evidence of an equalising score during the match.
"""

    prompt = f'''
You are a senior Gaelic football and hurling performance analyst.

Your task is to produce evidence-based tactical analysis.

{result_guardrail}

IMPORTANT ANALYSIS RULES:
- Treat HARD MATCH FACTS as deterministic truth, not soft context.
- Use actual team names throughout.
- Analyse from the perspective of {coached_team}.
- Explain WHY the result happened based on the scoreline and available evidence.
- Separate hard facts from uncertain visual inference.
- Never invent exact events, possessions, scores, equalisers or player identities.
- Avoid generic filler such as "rollercoaster", "dynamic movement", "communication gaps", "spatial awareness" unless supported by evidence.
- Every training recommendation must connect to a specific observed issue or scoreline implication.
- Prefer concise tactical insight over long prose.

MATCH CONTEXT
{match_context}

VIDEO INFORMATION
Title: {metadata['title']}
Uploader: {metadata['uploader']}
Duration: {metadata['duration']} seconds
Description: {metadata['description']}

MATCH URL
{request.url}

TRANSCRIPT / COMMENTARY
{transcript[:10000]}

VISUAL FRAME OBSERVATIONS
{visual_observations[:12000]}

COACH NOTES
{request.notes}

Return a concise premium coaching report with these exact sections:

# Result Snapshot
- one paragraph using scoreline, winner, margin and result type

# Why {coached_team} {match_facts['coachedTeamResult']}
- explain the main tactical reasons, grounded in scoreline and available evidence

# Strengths Shown By {coached_team}
- maximum 4 specific strengths
- each bullet must include: observation, impact, coaching implication

# Weaknesses / Risks For {coached_team}
- maximum 4 specific weaknesses or risks
- do not overstate weaknesses if the coached team won comfortably

# What Hurt {opposition_team}
- explain what likely made the match difficult for the opposition

# Tactical Themes Worth Reviewing
- only include themes supported by transcript, frames, notes or scoreline

# Training Priorities
- maximum 4 practical session priorities
- include drill type or session structure

# Confidence Notes
- High confidence: scoreline-derived conclusions
- Medium confidence: frame/transcript-supported tactical patterns
- Low confidence: anything not directly visible or timestamped

Keep headings clean and professional.
Do not use markdown bold inside bullet headings.
Do not repeat the executive summary inside other sections.
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {
                'role': 'system',
                'content': 'You are an elite Gaelic games tactical analyst. You obey hard scoreline facts, avoid contradictions, and produce evidence-first coaching intelligence.'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ]
    )

    analysis = response.choices[0].message.content

    return {
        'status': 'complete',
        'mode': 'worker',
        'analysis': analysis,
        'videoMetadata': metadata,
        'matchFacts': match_facts,
        'transcriptLength': len(transcript),
        'visualAnalysisLength': len(visual_observations),
        'framesSampledTarget': 60,
        'next_stage': 'Future upgrade: timestamped event detection, tactical tagging and clip generation.'
    }
