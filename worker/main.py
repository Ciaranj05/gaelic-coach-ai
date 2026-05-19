from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os, yt_dlp, uuid, tempfile, subprocess, base64, json
from datetime import datetime

app = FastAPI(title='Gaelic Coach AI Worker')
CLIP_ROOT = '/tmp/gaelic-coach-ai-clips'
os.makedirs(CLIP_ROOT, exist_ok=True)

class AnalyseRequest(BaseModel):
    url: str
    notes: str | None = ''
    matchContext: dict | None = None

jobs = {}
EVENT_TYPES = ['kickout_restart','turnover','fast_transition','scoring_chance','score_or_restart_after_score','defensive_setup','breaking_ball','slow_possession','game_management','not_useful']
SCORE_OUTCOMES = ['point','goal','wide','save','blocked','unknown']
PROGRESS_STAGES = {
    'queued': {'percent': 5, 'label': 'Queued for analysis'},
    'metadata': {'percent': 12, 'label': 'Reading match metadata'},
    'download': {'percent': 22, 'label': 'Downloading match video'},
    'full_match_scan': {'percent': 38, 'label': 'Scanning full match frames'},
    'event_selection': {'percent': 55, 'label': 'Selecting key review moments'},
    'event_analysis': {'percent': 72, 'label': 'Classifying tactical events, team colours and score outcomes'},
    'clip_extraction': {'percent': 82, 'label': 'Creating review clips'},
    'report': {'percent': 92, 'label': 'Building Gaelic football report'},
    'complete': {'percent': 100, 'label': 'Report ready'},
    'failed': {'percent': 100, 'label': 'Analysis failed'}
}

@app.get('/')
def health():
    return {'status': 'running', 'service': 'gaelic-coach-ai-worker'}

@app.get('/openai-status')
def openai_status():
    has_key = bool(os.getenv('OPENAI_API_KEY'))
    return {'connected': has_key, 'status': 'configured' if has_key else 'missing_key'}

def set_job_stage(job_id, stage, detail=None):
    if not job_id or job_id not in jobs: return
    jobs[job_id]['stage'] = stage
    jobs[job_id]['progress'] = PROGRESS_STAGES.get(stage, PROGRESS_STAGES['queued'])
    jobs[job_id]['detail'] = detail or jobs[job_id]['progress']['label']
    jobs[job_id]['updatedAt'] = datetime.utcnow().isoformat()

def is_veo_url(url): return 'veo.co' in url.lower()

def processing_profile(url):
    if is_veo_url(url):
        return {'name':'quick-veo','scanIntervalSeconds':2,'eventFramePack':6,'videoFormat':'best[height<=360]/best','clipCount':4}
    return {'name':'standard','scanIntervalSeconds':1,'eventFramePack':8,'videoFormat':'best[height<=480]/best','clipCount':6}

def format_timestamp(seconds):
    seconds = max(0, int(seconds or 0))
    return f'{seconds//60:02d}:{seconds%60:02d}'

def parse_json_safely(text):
    try: return json.loads(text)
    except Exception:
        try: return json.loads(text[text.index('{'):text.rindex('}')+1])
        except Exception: return None

def image_content_from_paths(paths):
    content=[]
    for item in paths:
        path = item['path'] if isinstance(item, dict) else item
        with open(path,'rb') as f: enc = base64.b64encode(f.read()).decode('utf-8')
        content.append({'type':'image_url','image_url':{'url':f'data:image/jpeg;base64,{enc}','detail':'low'}})
    return content

def extract_video_metadata(url):
    try:
        with yt_dlp.YoutubeDL({'quiet':True,'skip_download':True,'nocheckcertificate':True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {'title':info.get('title',''),'description':info.get('description',''),'uploader':info.get('uploader',''),'duration':info.get('duration',0),'filesize':info.get('filesize') or info.get('filesize_approx') or 0}
    except Exception:
        return {'title':'','description':'','uploader':'','duration':0,'filesize':0}

def build_match_facts(ctx):
    ctx = ctx or {}
    ta,tb,coached = ctx.get('teamA','Team A'), ctx.get('teamB','Team B'), ctx.get('coachedTeam', ctx.get('teamA','Team A'))
    ag,ap,bg,bp = int(ctx.get('teamAGoals') or 0), int(ctx.get('teamAPoints') or 0), int(ctx.get('teamBGoals') or 0), int(ctx.get('teamBPoints') or 0)
    at,bt = ag*3+ap, bg*3+bp
    winner,margin = ('Draw',0) if at==bt else ((ta,at-bt) if at>bt else (tb,bt-at))
    result = 'drew' if winner=='Draw' else ('won' if winner==coached else 'lost')
    cg,og = (ag,bg) if coached==ta else (bg,ag)
    cp,op = (ap,bp) if coached==ta else (bp,ap)
    ct,ot = (at,bt) if coached==ta else (bt,at)
    return {'teamA':ta,'teamB':tb,'coachedTeam':coached,'winner':winner,'margin':margin,'coachedTeamResult':result,'teamAGoals':ag,'teamBGoals':bg,'teamAPoints':ap,'teamBPoints':bp,'teamATotal':at,'teamBTotal':bt,'coachedGoals':cg,'oppositionGoals':og,'coachedPoints':cp,'oppositionPoints':op,'coachedTotal':ct,'oppositionTotal':ot,'goalDifference':cg-og,'scoreline':f'{ta} {ag}-{ap} ({at}) vs {tb} {bg}-{bp} ({bt})'}

def build_scoreline_rules(f):
    t=f['coachedTeam']; rules=[]
    if f['coachedGoals']>=5:
        rules += [f'{t} scored {f["coachedGoals"]} goals. Treat goal scoring and attacking penetration as strengths; do not recommend finishing practice unless notes say chances were wasted.', f'For {t}, focus on sustaining attacking patterns, game management, rest defence, kickout control and protection against counters.']
    elif f['coachedGoals']<=1 and f['coachedTeamResult']!='won': rules.append(f'{t} had limited goal output; focus can include high-value chance creation and earlier delivery into scoring zones.')
    if f['oppositionGoals']>=3: rules.append(f'{t} conceded {f["oppositionGoals"]} goals; prioritise defensive transition, central goal channels, sweeper cover and recovery shape.')
    elif f['oppositionGoals']<=1: rules.append(f'{t} conceded {f["oppositionGoals"]} goals; frame defensive work as refinement, not collapse.')
    if f['coachedTeamResult']=='won' and f['margin']>=10: rules.append(f'{t} won comfortably; focus on sustaining strengths and tightening risk areas.')
    if f['coachedTeamResult']=='lost' and f['margin']<=3: rules.append(f'{t} lost narrowly; focus on small swing factors and late-game decisions.')
    return '\n'.join('- '+r for r in rules) or '- Apply normal Gaelic football scoreline reasoning.'

def norm_scoreboard(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {'visible':bool(raw.get('visible',False)),'text':str(raw.get('text',''))[:160],'scoreChangeLikely':bool(raw.get('scoreChangeLikely',False)),'possibleScoreEvent':bool(raw.get('possibleScoreEvent',False)),'confidence':raw.get('confidence','low') if raw.get('confidence') in ['low','medium','high'] else 'low','ocrText':str(raw.get('ocrText',''))[:160],'ocrZones':raw.get('ocrZones',[]) if isinstance(raw.get('ocrZones',[]),list) else []}

def norm_score_outcome(raw):
    raw = raw if isinstance(raw, dict) else {}; cues = raw.get('cues',{}) if isinstance(raw.get('cues',{}),dict) else {}
    return {'outcome': raw.get('outcome') if raw.get('outcome') in SCORE_OUTCOMES else 'unknown','confidence': raw.get('confidence') if raw.get('confidence') in ['low','medium','high'] else 'low','evidence': (raw.get('evidence',[]) if isinstance(raw.get('evidence',[]),list) else [])[:8],'reasoning': str(raw.get('reasoning',''))[:300],'cues': {'scoreboardChange':bool(cues.get('scoreboardChange',False)),'umpireSignal':str(cues.get('umpireSignal','not_visible'))[:80],'ballPath':str(cues.get('ballPath','unclear'))[:80],'netMovement':bool(cues.get('netMovement',False)),'goalkeeperRetrieval':bool(cues.get('goalkeeperRetrieval',False)),'goalkeeperRestart':bool(cues.get('goalkeeperRestart',False)),'playerReaction':str(cues.get('playerReaction','unclear'))[:120],'cameraReset':bool(cues.get('cameraReset',False)),'crowdReaction':str(cues.get('crowdReaction','not_available'))[:80]}}

def norm_team_colours(raw, facts):
    raw = raw if isinstance(raw, dict) else {}
    return {'teamA': facts['teamA'], 'teamB': facts['teamB'], 'coachedTeam': facts['coachedTeam'], 'teamAColour': str(raw.get('teamAColour','unknown'))[:80], 'teamBColour': str(raw.get('teamBColour','unknown'))[:80], 'coachedTeamColour': str(raw.get('coachedTeamColour','unknown'))[:80], 'oppositionColour': str(raw.get('oppositionColour','unknown'))[:80], 'confidence': raw.get('confidence','low') if raw.get('confidence') in ['low','medium','high'] else 'low', 'visibleKits': raw.get('visibleKits',[]) if isinstance(raw.get('visibleKits',[]),list) else [], 'reasoning': str(raw.get('reasoning',''))[:300]}

def fallback_event_candidates(metadata):
    duration=int(metadata.get('duration') or 0); times=[360,1080,2160,3240] if duration<=0 else [int(duration*f) for f in [0.12,0.25,0.38,0.52,0.68,0.82]]
    labels=['kickout_restart','fast_transition','scoring_chance','breaking_ball','defensive_setup','game_management']
    return [{'time':f'{format_timestamp(s)} approx','startSecond':max(0,s-15),'endSecond':s+15,'type':labels[i%len(labels)],'reason':'Fallback checkpoint selected from match timeline.','confidence':'low','scoreOutcome':norm_score_outcome({})} for i,s in enumerate(times)]

def download_match_video(url,tmpdir,profile):
    path=os.path.join(tmpdir,'match.mp4')
    opts={'format':profile.get('videoFormat','best[height<=480]/best'),'outtmpl':path,'quiet':False,'noplaylist':True,'merge_output_format':'mp4','nocheckcertificate':True,'socket_timeout':30,'retries':2,'fragment_retries':2}
    with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
    return path if os.path.exists(path) else None

def scan_video_frame_differences(video_path, profile, max_scan_seconds=7200):
    interval=int(profile.get('scanIntervalSeconds',1)); w,h=64,36; size=w*h
    cmd=['ffmpeg','-i',video_path,'-vf',f'fps=1/{interval},scale={w}:{h},format=gray','-frames:v',str(max_scan_seconds//interval),'-f','rawvideo','-']
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL); prev=None; diffs=[]; idx=0
    try:
        while True:
            frame=p.stdout.read(size) if p.stdout else b''
            if not frame or len(frame)<size: break
            if prev is not None: diffs.append({'second':idx*interval,'difference':round(sum(abs(frame[i]-prev[i]) for i in range(size))/size,2)})
            prev=frame; idx+=1
    finally:
        try:p.kill()
        except Exception:pass
    return diffs

def classify_event_window(i):
    return ['kickout_restart','fast_transition','scoring_chance','score_or_restart_after_score','breaking_ball','defensive_setup','game_management','turnover','direct_ball_inside'][i%9]

def select_event_candidates_from_differences(differences, max_events=10):
    selected=[]
    for item in sorted(differences,key=lambda x:x['difference'],reverse=True):
        second=int(item['second'])
        if all(abs(second-e['startSecond'])>150 for e in selected):
            selected.append({'time':f'{format_timestamp(second)} approx','startSecond':max(0,second-20),'endSecond':second+25,'type':classify_event_window(len(selected)),'reason':f'Large visual change detected during full-match scan (frame difference {item["difference"]}).','confidence':'medium'})
        if len(selected)>=max_events: break
    return sorted(selected,key=lambda x:x['startSecond'])

def extract_event_frames(video_path,event,tmpdir,event_index,profile):
    count=int(profile.get('eventFramePack',8)); start=max(0,int(event.get('startSecond',0))); end=max(start+1,int(event.get('endSecond',start+30))); duration=max(1,end-start); fps=max(0.1,count/duration)
    pattern=os.path.join(tmpdir,f'event_{event_index}_%02d.jpg')
    subprocess.run(['ffmpeg','-y','-ss',str(start),'-i',video_path,'-t',str(duration),'-vf',f'fps={fps},scale=768:-1','-frames:v',str(count),pattern],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    return sorted([os.path.join(tmpdir,f) for f in os.listdir(tmpdir) if f.startswith(f'event_{event_index}_') and f.endswith('.jpg')])[:count]

def extract_scoreboard_crops(video_path,event,tmpdir,event_index):
    start=max(0,int(event.get('startSecond',0))); end=max(start+1,int(event.get('endSecond',start+30))); ts=start+max(1,int((end-start)/2))
    specs=[('top_left','crop=iw*0.42:ih*0.18:0:0,scale=900:-1'),('top_right','crop=iw*0.42:ih*0.18:iw*0.58:0,scale=900:-1'),('top_full','crop=iw:ih*0.20:0:0,scale=1200:-1')]
    crops=[]
    for name,vf in specs:
        out=os.path.join(tmpdir,f'ocr_{event_index}_{name}.jpg'); subprocess.run(['ffmpeg','-y','-ss',str(ts),'-i',video_path,'-frames:v','1','-vf',vf,out],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        if os.path.exists(out): crops.append({'zone':name,'path':out})
    return crops

def extract_event_clip(video_path,event,job_id,event_index):
    if not job_id: return None
    d=os.path.join(CLIP_ROOT,job_id); os.makedirs(d,exist_ok=True); start=max(0,int(event.get('startSecond',0))); end=max(start+1,int(event.get('endSecond',start+30))); dur=min(45,max(8,end-start)); cid=f'clip_{event_index:02d}'; out=os.path.join(d,f'{cid}.mp4')
    subprocess.run(['ffmpeg','-y','-ss',str(start),'-i',video_path,'-t',str(dur),'-vf','scale=640:-2','-c:v','libx264','-preset','veryfast','-crf','30','-an','-movflags','+faststart',out],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    return None if not os.path.exists(out) else {'clipId':cid,'filename':f'{cid}.mp4','startSecond':start,'endSecond':start+dur,'duration':dur,'time':f'{format_timestamp(start)}–{format_timestamp(start+dur)} approx','type':event.get('type','review clip'),'downloadPath':f'/analysis-jobs/{job_id}/clips/{cid}'}

def detect_team_colours(client, frame_paths, facts):
    if not frame_paths: return norm_team_colours({}, facts)
    content=[{'type':'text','text':f'''Detect the two main team kit colours in this Gaelic football footage. Team A: {facts['teamA']}. Team B: {facts['teamB']}. Coached team: {facts['coachedTeam']}.
Return JSON only: {{"teamAColour":"colour or unknown","teamBColour":"colour or unknown","coachedTeamColour":"colour or unknown","oppositionColour":"colour or unknown","visibleKits":["colour 1","colour 2"],"confidence":"low|medium|high","reasoning":"short reason"}}.
Use coach notes/team names only if the footage supports it. If you cannot map colours to teams, list visibleKits but keep team colours unknown.'''}]
    content += image_content_from_paths(frame_paths[:6])
    res=client.chat.completions.create(model='gpt-4o-mini',response_format={'type':'json_object'},messages=[{'role':'user','content':content}])
    return norm_team_colours(parse_json_safely(res.choices[0].message.content or '{}') or {}, facts)

def read_scoreboard_ocr(client,crops):
    if not crops: return norm_scoreboard({})
    content=[{'type':'text','text':'Read any visible Gaelic football scoreboard/score bug. Return JSON only: {"visible":true,"ocrText":"exact readable text","ocrZones":["top_left"],"confidence":"low|medium|high"}. If none, return visible false. Do not guess.'}]+image_content_from_paths(crops)
    res=client.chat.completions.create(model='gpt-4o-mini',response_format={'type':'json_object'},messages=[{'role':'user','content':content}])
    p=parse_json_safely(res.choices[0].message.content or '{}') or {}
    return norm_scoreboard({'visible':p.get('visible'),'ocrText':p.get('ocrText',''),'text':p.get('ocrText',''),'ocrZones':p.get('ocrZones',[]),'confidence':p.get('confidence','low')})

def classify_event_frames(client, frame_paths, event, scoreboard_ocr, team_colours):
    if not frame_paths:
        return {'eventType':event.get('type','not_useful'),'confidence':'low','coachingValue':'low','keepForReport':False,'visibleCues':[],'coachingReason':'No frames available.','visualSummary':'','scoreboard':scoreboard_ocr,'scoreOutcome':norm_score_outcome({}),'teamColours':team_colours}
    content=[{'type':'text','text':f'''Classify this Gaelic football review window using only visible evidence.
Candidate: {event.get('time')} / {event.get('type')}
Scoreboard OCR: {scoreboard_ocr}
Team colour evidence: {team_colours}
Return JSON only with: eventType(one of {EVENT_TYPES}), confidence(low|medium|high), coachingValue(low|medium|high), keepForReport(boolean), visibleCues(array), coachingReason, visualSummary, scoreboard object, scoreOutcome object, possessionColour("colour|unknown"), likelyTeamInPossession("team name|unknown").
scoreOutcome.outcome must be one of {SCORE_OUTCOMES}. Only call point/goal with strong evidence; use unknown if unclear. Use team colour evidence conservatively; if not clear, say unknown.'''}]
    content += image_content_from_paths(frame_paths)
    res=client.chat.completions.create(model='gpt-4o-mini',response_format={'type':'json_object'},messages=[{'role':'user','content':content}])
    p=parse_json_safely(res.choices[0].message.content or '{}') or {}; sb=norm_scoreboard({**scoreboard_ocr, **(p.get('scoreboard',{}) if isinstance(p.get('scoreboard'),dict) else {})}); so=norm_score_outcome(p.get('scoreOutcome',{}))
    et=p.get('eventType') if p.get('eventType') in EVENT_TYPES else event.get('type','not_useful')
    if so['outcome'] in ['point','goal','wide'] or sb['possibleScoreEvent']:
        if et not in ['scoring_chance','score_or_restart_after_score']: et='score_or_restart_after_score'
    return {'eventType':et,'confidence':p.get('confidence','low'),'coachingValue':p.get('coachingValue','medium'),'keepForReport':bool(p.get('keepForReport',et!='not_useful')),'visibleCues':p.get('visibleCues',[]) if isinstance(p.get('visibleCues',[]),list) else [],'coachingReason':p.get('coachingReason',''),'visualSummary':p.get('visualSummary',''),'scoreboard':sb,'scoreOutcome':so,'teamColours':team_colours,'possessionColour':str(p.get('possessionColour','unknown'))[:80],'likelyTeamInPossession':str(p.get('likelyTeamInPossession','unknown'))[:120]}

def build_event_candidates(url, metadata, profile, client=None, job_id=None, facts=None):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            set_job_stage(job_id,'download','Downloading match video for full-match scan'); video_path=download_match_video(url,tmpdir,profile)
            if not video_path: return fallback_event_candidates(metadata)
            set_job_stage(job_id,'full_match_scan','Extracting low-res scan frames and comparing movement changes'); diffs=scan_video_frame_differences(video_path,profile)
            set_job_stage(job_id,'event_selection','Selecting strongest candidate review windows'); candidates=select_event_candidates_from_differences(diffs) or fallback_event_candidates(metadata)
            if not client: return candidates
            set_job_stage(job_id,'event_analysis','Detecting team colours, score outcomes and tactical event types')
            enriched=[]; clip_count=int(profile.get('clipCount',6)); first_frames=[]
            for i,event in enumerate(candidates[:clip_count], start=1):
                frames=extract_event_frames(video_path,event,tmpdir,i,profile)
                if frames and len(first_frames)<8: first_frames += frames[:2]
                team_colours=detect_team_colours(client, first_frames or frames, facts or build_match_facts({}))
                scoreboard_ocr=read_scoreboard_ocr(client, extract_scoreboard_crops(video_path,event,tmpdir,i))
                classification=classify_event_frames(client,frames,event,scoreboard_ocr,team_colours)
                if not classification.get('keepForReport') and classification.get('coachingValue')=='low': continue
                et=classification.get('eventType',event.get('type')); clip=extract_event_clip(video_path,{**event,'type':et},job_id,i)
                enriched.append({**event,'type':et,'classification':classification,'visualAnalysis':classification.get('visualSummary',''),'scoreboard':classification.get('scoreboard'),'scoreOutcome':classification.get('scoreOutcome'),'teamColours':classification.get('teamColours'),'possessionColour':classification.get('possessionColour'),'likelyTeamInPossession':classification.get('likelyTeamInPossession'),'framesAnalysed':len(frames),'clip':clip})
            return enriched + candidates[clip_count:]
    except Exception:
        return fallback_event_candidates(metadata)

def build_report_prompt(coached, opposition, facts, rules, metadata, events, notes, profile):
    return f'''You are an elite Gaelic football performance analyst working directly for {coached}.
Create a short Gaelic football manager debrief for {coached}. Use classified event evidence, team colour evidence, score outcome cues, OCR scoreboard reads and clips as approximate evidence.
MATCH FACTS: {facts}
SCORELINE RULES: {rules}
VIDEO METADATA: {metadata}
CLASSIFIED EVENTS: {events}
COACH NOTES: {notes}
PROFILE: {profile}
Rules: This is Gaelic football. Use kickouts, breaking ball, middle third, runners from deep, direct ball inside, D protection, counter-press, kick-pass threat, shot selection, game management. Team colour evidence is approximate; never overclaim possession if unclear. Never contradict final scoreline or invent scorers.
Return this exact markdown structure:
# {coached} – Match Snapshot
| Item | Detail |
|---|---|
| Scoreline | {facts['scoreline']} |
| Result | {coached} {facts['coachedTeamResult']} by {facts['margin']} point(s) |
| Core Story | One direct Gaelic football tactical sentence. |

# {coached} – Match-Deciding Factor
One blunt Gaelic football paragraph, max 45 words.

# {coached} – Estimated Key Match Stats
| Metric | {coached} | {opposition} |
|---|---|---|
| Possession | estimated range/label + colour/phase evidence if available + ✅/⚠️/❌ | estimated range/label + colour/phase evidence if available + ✅/⚠️/❌ |
| Shot Creation | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Goal Threat | {facts['coachedGoals']} goals + tactical label + ✅/⚠️/❌ | {facts['oppositionGoals']} goals + tactical label + ✅/⚠️/❌ |
| Point Output | {facts['coachedPoints']} points + tactical label + ✅/⚠️/❌ | {facts['oppositionPoints']} points + tactical label + ✅/⚠️/❌ |
| Scoring Bursts | use score outcome cues if available | use score outcome cues if available |
| Kickout / Restart Retention | estimated label + colour evidence if available + ✅/⚠️/❌ | estimated label + colour evidence if available + ✅/⚠️/❌ |
| Breaking Ball | estimated label + observation + ✅/⚠️/❌ | estimated label + observation + ✅/⚠️/❌ |

# {coached} – Tactical Comparison
| Area | {coached} | {opposition} |
|---|---|---|
| Transition Through Middle Third | observation + ✅/⚠️/❌ | observation + ✅/⚠️/❌ |
| Direct Ball Inside | observation + ✅/⚠️/❌ | observation + ✅/⚠️/❌ |
| Kick-Pass Threat | observation + ✅/⚠️/❌ | observation + ✅/⚠️/❌ |
| Shot Selection | observation + ✅/⚠️/❌ | observation + ✅/⚠️/❌ |
| Turnovers / Counter-Press | observation + ✅/⚠️/❌ | observation + ✅/⚠️/❌ |
| Kickout Platform | observation + ✅/⚠️/❌ | observation + ✅/⚠️/❌ |
| D Protection / Defensive Screen | observation + ✅/⚠️/❌ | observation + ✅/⚠️/❌ |

# {coached} – Review Clips
| Clip | Event Type | Score Outcome | Team / Colour Cue | Why Review It |
|---|---|---|---|---|
| Use available clip links from classified events | event type | point/goal/wide/save/blocked/unknown | team/colour cue or unknown | one specific coaching reason |

# {coached} – Main Focus Areas Going Forward
| Priority | Why It Matters For {coached} | Coaching Action |
|---|---|---|
| Specific Gaelic football focus 1 | match-specific reason | practical action |
| Specific Gaelic football focus 2 | match-specific reason | practical action |
| Specific Gaelic football focus 3 | match-specific reason | practical action |

# {coached} – Key Manager Takeaway
One short quote, max 55 words.'''

def generate_analysis(request, job_id=None):
    api_key=os.getenv('OPENAI_API_KEY')
    if not api_key: raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')
    client=OpenAI(api_key=api_key); profile=processing_profile(request.url); facts=build_match_facts(request.matchContext or {})
    set_job_stage(job_id,'metadata','Reading video title, duration and match metadata'); metadata=extract_video_metadata(request.url)
    events=build_event_candidates(request.url, metadata, profile, client, job_id, facts)
    set_job_stage(job_id,'clip_extraction','Review clips created for selected moments')
    coached=facts['coachedTeam']; opposition=facts['teamB'] if facts['teamA']==coached else facts['teamA']
    prompt=build_report_prompt(coached,opposition,facts,build_scoreline_rules(facts),metadata,events,request.notes,profile)
    set_job_stage(job_id,'report','Building final manager debrief report')
    res=client.chat.completions.create(model='gpt-4o-mini',messages=[{'role':'system','content':'You produce concise Gaelic football manager debrief reports using classified event evidence, team colour evidence, score outcomes and scoreline-aware tactical insights.'},{'role':'user','content':prompt}])
    clips=[e.get('clip') for e in events if isinstance(e,dict) and e.get('clip')]
    classifications=[e.get('classification') for e in events if isinstance(e,dict) and e.get('classification')]
    team_colours=[e.get('teamColours') for e in events if isinstance(e,dict) and e.get('teamColours')]
    scoring=[e for e in events if isinstance(e,dict) and e.get('scoreOutcome',{}).get('outcome')!='unknown']
    return {'status':'complete','mode':'worker','analysis':res.choices[0].message.content,'videoMetadata':metadata,'matchFacts':facts,'processingProfile':profile['name'],'eventCandidates':events,'eventClassifications':classifications,'teamColours':team_colours,'scoringCues':scoring,'clips':clips}

def run_analysis_job(job_id, request):
    try:
        jobs[job_id]['result']=generate_analysis(request,job_id); jobs[job_id]['status']='complete'; set_job_stage(job_id,'complete','Report ready')
    except Exception as exc:
        jobs[job_id]['status']='failed'; jobs[job_id]['error']=str(exc); set_job_stage(job_id,'failed','Analysis failed')

@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest): return generate_analysis(request)

@app.post('/analysis-jobs')
def create_analysis_job(request: AnalyseRequest, background_tasks: BackgroundTasks):
    job_id=str(uuid.uuid4()); jobs[job_id]={'jobId':job_id,'status':'processing','stage':'queued','progress':PROGRESS_STAGES['queued'],'detail':'Queued for analysis','createdAt':datetime.utcnow().isoformat(),'updatedAt':datetime.utcnow().isoformat(),'result':None,'error':None}
    background_tasks.add_task(run_analysis_job,job_id,request)
    return {'jobId':job_id,'status':'processing','progress':PROGRESS_STAGES['queued']}

@app.get('/analysis-jobs/{job_id}')
def get_analysis_job(job_id: str):
    if job_id not in jobs: raise HTTPException(status_code=404, detail='Job not found')
    return jobs[job_id]

@app.get('/analysis-jobs/{job_id}/clips/{clip_id}')
def download_clip(job_id: str, clip_id: str):
    clip_path=os.path.join(CLIP_ROOT,job_id,f'{clip_id}.mp4')
    if not os.path.exists(clip_path): raise HTTPException(status_code=404, detail='Clip not found or expired')
    return FileResponse(clip_path, media_type='video/mp4', filename=f'{clip_id}.mp4')
