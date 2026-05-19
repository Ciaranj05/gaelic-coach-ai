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
KICKOUT_OUTCOMES = ['short_retained','won_clean','won_breaking_ball','lost_clean','lost_breaking_ball','pressed_into_turnover','contested_unknown','not_kickout','unknown']
POSSESSION_OUTCOMES = ['retained','lost','won_back','turnover_for','turnover_against','unclear']
TRANSITION_OUTCOMES = ['created_score','created_chance','carried_to_scoring_zone','slowed_down','forced_backwards','turned_over','conceded_counter','not_transition','unknown']
FIELD_ZONES = ['defensive_third','middle_third','attacking_third','scoring_zone','left_channel','right_channel','central_channel','wide_channel','unknown']
MOMENTUM_LABELS = ['dominant_spell','pressure_spell','scoring_burst','defensive_stand','settled_phase','unclear']
PROGRESS_STAGES = {
    'queued': {'percent': 5, 'label': 'Queued for analysis'},
    'metadata': {'percent': 12, 'label': 'Reading match metadata'},
    'download': {'percent': 22, 'label': 'Downloading match video'},
    'full_match_scan': {'percent': 36, 'label': 'Scanning full match frames'},
    'event_selection': {'percent': 52, 'label': 'Selecting tactical review windows'},
    'event_analysis': {'percent': 72, 'label': 'Building sequences, possession continuity, zones and momentum'},
    'clip_extraction': {'percent': 84, 'label': 'Creating review clips'},
    'report': {'percent': 92, 'label': 'Building sequence-led Gaelic football report'},
    'complete': {'percent': 100, 'label': 'Report ready'},
    'failed': {'percent': 100, 'label': 'Analysis failed'}
}

@app.get('/')
def health(): return {'status': 'running', 'service': 'gaelic-coach-ai-worker'}

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
        return {'name':'quick-veo','scanIntervalSeconds':2,'eventFramePack':6,'videoFormat':'best[height<=360]/best','candidateCount':24,'classifiedEventCount':12,'clipCount':6,'minEventGapSeconds':75}
    return {'name':'standard','scanIntervalSeconds':1,'eventFramePack':6,'videoFormat':'best[height<=480]/best','candidateCount':42,'classifiedEventCount':26,'clipCount':8,'minEventGapSeconds':55}

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
    if f['coachedTeamResult']=='won' and f['margin']>=10: rules.append(f'{t} won comfortably; focus on sustaining strengths, game management and tightening risk areas.')
    if f['coachedTeamResult']=='lost' and f['margin']<=3: rules.append(f'{t} lost narrowly; focus on small swing factors and late-game decisions.')
    return '\n'.join('- '+r for r in rules) or '- Apply normal Gaelic football scoreline reasoning.'

def norm_choice(value, allowed, default='unknown'):
    return value if value in allowed else default

def norm_scoreboard(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {'visible':bool(raw.get('visible',False)),'text':str(raw.get('text',''))[:160],'scoreChangeLikely':bool(raw.get('scoreChangeLikely',False)),'possibleScoreEvent':bool(raw.get('possibleScoreEvent',False)),'confidence':norm_choice(raw.get('confidence'),['low','medium','high'],'low'),'ocrText':str(raw.get('ocrText',''))[:160],'ocrZones':raw.get('ocrZones',[]) if isinstance(raw.get('ocrZones',[]),list) else []}

def norm_score_outcome(raw):
    raw = raw if isinstance(raw, dict) else {}; cues = raw.get('cues',{}) if isinstance(raw.get('cues',{}),dict) else {}
    return {'outcome': norm_choice(raw.get('outcome'), SCORE_OUTCOMES),'confidence': norm_choice(raw.get('confidence'), ['low','medium','high'],'low'),'evidence': (raw.get('evidence',[]) if isinstance(raw.get('evidence',[]),list) else [])[:8],'reasoning': str(raw.get('reasoning',''))[:300],'cues': {'scoreboardChange':bool(cues.get('scoreboardChange',False)),'umpireSignal':str(cues.get('umpireSignal','not_visible'))[:80],'ballPath':str(cues.get('ballPath','unclear'))[:80],'netMovement':bool(cues.get('netMovement',False)),'goalkeeperRetrieval':bool(cues.get('goalkeeperRetrieval',False)),'goalkeeperRestart':bool(cues.get('goalkeeperRestart',False)),'playerReaction':str(cues.get('playerReaction','unclear'))[:120],'cameraReset':bool(cues.get('cameraReset',False)),'crowdReaction':str(cues.get('crowdReaction','not_available'))[:80]}}

def norm_team_colours(raw, facts):
    raw = raw if isinstance(raw, dict) else {}
    return {'teamA': facts['teamA'], 'teamB': facts['teamB'], 'coachedTeam': facts['coachedTeam'], 'teamAColour': str(raw.get('teamAColour','unknown'))[:80], 'teamBColour': str(raw.get('teamBColour','unknown'))[:80], 'coachedTeamColour': str(raw.get('coachedTeamColour','unknown'))[:80], 'oppositionColour': str(raw.get('oppositionColour','unknown'))[:80], 'confidence': norm_choice(raw.get('confidence'),['low','medium','high'],'low'), 'visibleKits': raw.get('visibleKits',[]) if isinstance(raw.get('visibleKits',[]),list) else [], 'reasoning': str(raw.get('reasoning',''))[:300]}

def norm_match_intel(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        'kickoutOutcome': norm_choice(raw.get('kickoutOutcome'), KICKOUT_OUTCOMES),
        'kickoutTeam': str(raw.get('kickoutTeam','unknown'))[:120],
        'possessionStart': str(raw.get('possessionStart','unknown'))[:120],
        'possessionEnd': str(raw.get('possessionEnd','unknown'))[:120],
        'possessionOutcome': norm_choice(raw.get('possessionOutcome'), POSSESSION_OUTCOMES, 'unclear'),
        'turnoverTeam': str(raw.get('turnoverTeam','unknown'))[:120],
        'transitionOutcome': norm_choice(raw.get('transitionOutcome'), TRANSITION_OUTCOMES),
        'transitionTeam': str(raw.get('transitionTeam','unknown'))[:120],
        'confidence': norm_choice(raw.get('confidence'), ['low','medium','high'], 'low'),
        'evidence': (raw.get('evidence',[]) if isinstance(raw.get('evidence',[]),list) else [])[:8],
        'coachingValue': norm_choice(raw.get('coachingValue'), ['low','medium','high'], 'medium'),
        'timelineGroup': norm_choice(raw.get('timelineGroup'), ['scores','wides','kickouts','turnovers','transitions','defence','possession','other'], 'other'),
        'fieldZone': norm_choice(raw.get('fieldZone'), FIELD_ZONES),
        'startZone': norm_choice(raw.get('startZone'), FIELD_ZONES),
        'endZone': norm_choice(raw.get('endZone'), FIELD_ZONES),
        'momentumCue': norm_choice(raw.get('momentumCue'), MOMENTUM_LABELS, 'unclear'),
        'sequenceRole': norm_choice(raw.get('sequenceRole'), ['start','middle','end','standalone','unknown'])
    }

def fallback_event_candidates(metadata):
    duration=int(metadata.get('duration') or 0); times=[360,1080,2160,3240] if duration<=0 else [int(duration*f) for f in [0.10,0.18,0.26,0.34,0.42,0.50,0.58,0.66,0.74,0.84]]
    labels=['kickout_restart','fast_transition','scoring_chance','breaking_ball','defensive_setup','game_management']
    return [{'time':f'{format_timestamp(s)} approx','startSecond':max(0,s-18),'endSecond':s+24,'type':labels[i%len(labels)],'reason':'Fallback checkpoint selected from match timeline.','confidence':'low','scoreOutcome':norm_score_outcome({}),'matchIntelligence':norm_match_intel({})} for i,s in enumerate(times)]

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
            if prev is not None:
                diff=sum(abs(frame[i]-prev[i]) for i in range(size))/size
                # smooth visual movement into a football-useful intensity score
                diffs.append({'second':idx*interval,'difference':round(diff,2),'intensity':round(min(100, diff*1.4),2)})
            prev=frame; idx+=1
    finally:
        try:p.kill()
        except Exception:pass
    return diffs

def classify_event_window(i):
    return ['kickout_restart','fast_transition','scoring_chance','score_or_restart_after_score','breaking_ball','defensive_setup','game_management','turnover','direct_ball_inside'][i%9]

def select_event_candidates_from_differences(differences, max_events=36, min_gap_seconds=60):
    if not differences: return []
    selected=[]
    # Mix high-motion windows with regular match checkpoints so the system does not only find camera jumps.
    sorted_motion=sorted(differences,key=lambda x:x.get('intensity',x.get('difference',0)),reverse=True)
    for item in sorted_motion:
        second=int(item['second'])
        if all(abs(second-e['startSecond'])>min_gap_seconds for e in selected):
            selected.append({'time':f'{format_timestamp(second)} approx','startSecond':max(0,second-22),'endSecond':second+32,'type':classify_event_window(len(selected)),'reason':f'Tactical scan window selected from motion/intensity change ({item.get("intensity", item.get("difference"))}).','confidence':'medium'})
        if len(selected)>=max_events: break
    if len(selected) < max_events and differences:
        duration=max(int(d.get('second',0)) for d in differences)
        step=max(75, duration//max_events) if duration else 120
        second=step
        while len(selected)<max_events and second<duration:
            if all(abs(second-e['startSecond'])>min_gap_seconds for e in selected):
                selected.append({'time':f'{format_timestamp(second)} approx','startSecond':max(0,second-22),'endSecond':second+32,'type':classify_event_window(len(selected)),'reason':'Regular tactical checkpoint added to improve match coverage.','confidence':'low'})
            second+=step
    return sorted(selected,key=lambda x:x['startSecond'])

def extract_event_frames(video_path,event,tmpdir,event_index,profile):
    count=int(profile.get('eventFramePack',6)); start=max(0,int(event.get('startSecond',0))); end=max(start+1,int(event.get('endSecond',start+30))); duration=max(1,end-start); fps=max(0.1,count/duration)
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
    d=os.path.join(CLIP_ROOT,job_id); os.makedirs(d,exist_ok=True); start=max(0,int(event.get('startSecond',0))); end=max(start+1,int(event.get('endSecond',start+30))); dur=min(60,max(12,end-start)); cid=f'clip_{event_index:02d}'; out=os.path.join(d,f'{cid}.mp4')
    subprocess.run(['ffmpeg','-y','-ss',str(start),'-i',video_path,'-t',str(dur),'-vf','scale=640:-2','-c:v','libx264','-preset','veryfast','-crf','30','-an','-movflags','+faststart',out],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    return None if not os.path.exists(out) else {'clipId':cid,'filename':f'{cid}.mp4','startSecond':start,'endSecond':start+dur,'duration':dur,'time':f'{format_timestamp(start)}–{format_timestamp(start+dur)} approx','type':event.get('type','review clip'),'downloadPath':f'/analysis-jobs/{job_id}/clips/{cid}'}

def detect_team_colours(client, frame_paths, facts):
    if not frame_paths: return norm_team_colours({}, facts)
    content=[{'type':'text','text':f'''Detect the two main team kit colours in this Gaelic football footage. Team A: {facts['teamA']}. Team B: {facts['teamB']}. Coached team: {facts['coachedTeam']}.
Return JSON only: {{"teamAColour":"colour or unknown","teamBColour":"colour or unknown","coachedTeamColour":"colour or unknown","oppositionColour":"colour or unknown","visibleKits":["colour 1","colour 2"],"confidence":"low|medium|high","reasoning":"short reason"}}. If you cannot map colours to team names, keep team colours unknown but list visibleKits.'''}]
    content += image_content_from_paths(frame_paths[:6])
    res=client.chat.completions.create(model='gpt-4o-mini',response_format={'type':'json_object'},messages=[{'role':'user','content':content}])
    return norm_team_colours(parse_json_safely(res.choices[0].message.content or '{}') or {}, facts)

def read_scoreboard_ocr(client,crops):
    if not crops: return norm_scoreboard({})
    content=[{'type':'text','text':'Read any visible Gaelic football scoreboard/score bug. Return JSON only: {"visible":true,"ocrText":"exact readable text","ocrZones":["top_left"],"confidence":"low|medium|high"}. If none, return visible false. Do not guess.'}]+image_content_from_paths(crops)
    res=client.chat.completions.create(model='gpt-4o-mini',response_format={'type':'json_object'},messages=[{'role':'user','content':content}])
    p=parse_json_safely(res.choices[0].message.content or '{}') or {}
    return norm_scoreboard({'visible':p.get('visible'),'ocrText':p.get('ocrText',''),'text':p.get('ocrText',''),'ocrZones':p.get('ocrZones',[]),'confidence':p.get('confidence','low')})

def classify_event_frames(client, frame_paths, event, scoreboard_ocr, team_colours, facts):
    if not frame_paths:
        return {'eventType':event.get('type','not_useful'),'confidence':'low','coachingValue':'low','keepForReport':False,'visibleCues':[],'coachingReason':'No frames available.','visualSummary':'','scoreboard':scoreboard_ocr,'scoreOutcome':norm_score_outcome({}),'teamColours':team_colours,'matchIntelligence':norm_match_intel({})}
    content=[{'type':'text','text':f'''Classify this Gaelic football review window using only visible evidence.
Candidate: {event.get('time')} / {event.get('type')}
Teams: {facts['teamA']} vs {facts['teamB']}. Coached team: {facts['coachedTeam']}.
Scoreboard OCR: {scoreboard_ocr}
Team colour evidence: {team_colours}
Return JSON only with keys:
eventType(one of {EVENT_TYPES}), confidence(low|medium|high), coachingValue(low|medium|high), keepForReport(boolean), visibleCues(array), coachingReason, visualSummary,
scoreboard object,
scoreOutcome: {{outcome(one of {SCORE_OUTCOMES}), confidence, evidence, reasoning, cues}},
matchIntelligence: {{kickoutOutcome(one of {KICKOUT_OUTCOMES}), kickoutTeam(team/unknown), possessionStart(team/colour/unknown), possessionEnd(team/colour/unknown), possessionOutcome(one of {POSSESSION_OUTCOMES}), turnoverTeam(team/unknown), transitionOutcome(one of {TRANSITION_OUTCOMES}), transitionTeam(team/unknown), confidence(low|medium|high), evidence(array), coachingValue(low|medium|high), timelineGroup(scores|wides|kickouts|turnovers|transitions|defence|possession|other), fieldZone(one of {FIELD_ZONES}), startZone(one of {FIELD_ZONES}), endZone(one of {FIELD_ZONES}), momentumCue(one of {MOMENTUM_LABELS}), sequenceRole(start|middle|end|standalone|unknown)}},
possessionColour("colour|unknown"), likelyTeamInPossession("team name|unknown").
Rules: be conservative. Only assign team ownership if colour evidence and frames support it. Track football meaning over the whole window: where it starts, where it ends, whether it is a kickout, possession chain, turnover, transition, defensive setup or scoring phase. Use field zones: defensive_third, middle_third, attacking_third, scoring_zone, channels. Use unknown if unclear.'''}]
    content += image_content_from_paths(frame_paths)
    res=client.chat.completions.create(model='gpt-4o-mini',response_format={'type':'json_object'},messages=[{'role':'user','content':content}])
    p=parse_json_safely(res.choices[0].message.content or '{}') or {}
    sb=norm_scoreboard({**scoreboard_ocr, **(p.get('scoreboard',{}) if isinstance(p.get('scoreboard'),dict) else {})}); so=norm_score_outcome(p.get('scoreOutcome',{})); mi=norm_match_intel(p.get('matchIntelligence',{}))
    et=p.get('eventType') if p.get('eventType') in EVENT_TYPES else event.get('type','not_useful')
    if so['outcome'] in ['point','goal','wide'] or sb['possibleScoreEvent']:
        if et not in ['scoring_chance','score_or_restart_after_score']: et='score_or_restart_after_score'
    if mi['kickoutOutcome'] not in ['not_kickout','unknown'] and et == 'not_useful': et='kickout_restart'
    if mi['possessionOutcome'] in ['turnover_for','turnover_against'] and et == 'not_useful': et='turnover'
    return {'eventType':et,'confidence':p.get('confidence','low'),'coachingValue':p.get('coachingValue',mi.get('coachingValue','medium')),'keepForReport':bool(p.get('keepForReport',et!='not_useful')),'visibleCues':p.get('visibleCues',[]) if isinstance(p.get('visibleCues',[]),list) else [],'coachingReason':p.get('coachingReason',''),'visualSummary':p.get('visualSummary',''),'scoreboard':sb,'scoreOutcome':so,'teamColours':team_colours,'matchIntelligence':mi,'possessionColour':str(p.get('possessionColour','unknown'))[:80],'likelyTeamInPossession':str(p.get('likelyTeamInPossession','unknown'))[:120]}

def build_event_candidates(url, metadata, profile, client=None, job_id=None, facts=None):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            set_job_stage(job_id,'download','Downloading match video for full-match scan'); video_path=download_match_video(url,tmpdir,profile)
            if not video_path: return fallback_event_candidates(metadata)
            set_job_stage(job_id,'full_match_scan','Extracting low-res scan frames and comparing movement changes'); diffs=scan_video_frame_differences(video_path,profile)
            set_job_stage(job_id,'event_selection','Selecting dense tactical review windows'); candidates=select_event_candidates_from_differences(diffs, int(profile.get('candidateCount',36)), int(profile.get('minEventGapSeconds',60))) or fallback_event_candidates(metadata)
            if not client: return candidates
            set_job_stage(job_id,'event_analysis','Classifying dense windows for possession, zones, momentum and score outcomes')
            enriched=[]; classified_count=int(profile.get('classifiedEventCount',24)); clip_count=int(profile.get('clipCount',8)); first_frames=[]; facts=facts or build_match_facts({}); cached_colours=None
            for i,event in enumerate(candidates[:classified_count], start=1):
                frames=extract_event_frames(video_path,event,tmpdir,i,profile)
                if frames and len(first_frames)<10: first_frames += frames[:2]
                if not cached_colours or cached_colours.get('confidence') == 'low': cached_colours=detect_team_colours(client, first_frames or frames, facts)
                scoreboard_ocr=read_scoreboard_ocr(client, extract_scoreboard_crops(video_path,event,tmpdir,i))
                classification=classify_event_frames(client,frames,event,scoreboard_ocr,cached_colours,facts)
                if not classification.get('keepForReport') and classification.get('coachingValue')=='low': continue
                et=classification.get('eventType',event.get('type'))
                clip=extract_event_clip(video_path,{**event,'type':et},job_id,i) if i <= clip_count else None
                enriched.append({**event,'type':et,'classification':classification,'visualAnalysis':classification.get('visualSummary',''),'scoreboard':classification.get('scoreboard'),'scoreOutcome':classification.get('scoreOutcome'),'teamColours':classification.get('teamColours'),'matchIntelligence':classification.get('matchIntelligence'),'possessionColour':classification.get('possessionColour'),'likelyTeamInPossession':classification.get('likelyTeamInPossession'),'framesAnalysed':len(frames),'clip':clip})
            return enriched + candidates[classified_count:]
    except Exception:
        return fallback_event_candidates(metadata)

def event_quality(e):
    if not isinstance(e, dict): return 0
    c=e.get('classification',{}) or {}; mi=e.get('matchIntelligence',{}) or {}; so=e.get('scoreOutcome',{}) or {}
    score=0
    if c.get('confidence')=='high': score+=3
    elif c.get('confidence')=='medium': score+=2
    if mi.get('confidence')=='high': score+=3
    elif mi.get('confidence')=='medium': score+=2
    if c.get('coachingValue')=='high' or mi.get('coachingValue')=='high': score+=2
    if so.get('outcome') not in [None,'unknown']: score+=2
    if mi.get('kickoutOutcome') not in [None,'unknown','not_kickout']: score+=2
    if mi.get('transitionOutcome') not in [None,'unknown','not_transition']: score+=2
    if mi.get('possessionOutcome') in ['turnover_for','turnover_against','won_back','lost']: score+=2
    if mi.get('fieldZone') not in [None,'unknown']: score+=1
    if e.get('likelyTeamInPossession') not in [None,'unknown','']: score+=1
    if e.get('clip'): score+=1
    return score

def build_timeline(events):
    groups={k:[] for k in ['scores','wides','kickouts','turnovers','transitions','defence','possession','other']}
    for e in events:
        if not isinstance(e,dict) or event_quality(e) < 3: continue
        so=e.get('scoreOutcome',{}) or {}; mi=e.get('matchIntelligence',{}) or {}; group=mi.get('timelineGroup','other')
        if so.get('outcome') in ['point','goal']: group='scores'
        elif so.get('outcome')=='wide': group='wides'
        elif mi.get('kickoutOutcome') not in [None,'not_kickout','unknown']: group='kickouts'
        elif mi.get('possessionOutcome') in ['turnover_for','turnover_against','lost','won_back']: group='turnovers'
        elif mi.get('transitionOutcome') not in [None,'not_transition','unknown']: group='transitions'
        item={'time':e.get('time'),'startSecond':e.get('startSecond'),'eventType':e.get('type'),'scoreOutcome':so.get('outcome','unknown'),'kickoutOutcome':mi.get('kickoutOutcome','unknown'),'possessionOutcome':mi.get('possessionOutcome','unclear'),'transitionOutcome':mi.get('transitionOutcome','unknown'),'fieldZone':mi.get('fieldZone','unknown'),'teamCue':e.get('likelyTeamInPossession','unknown'),'summary':e.get('visualAnalysis',''),'clip':e.get('clip')}
        groups[group if group in groups else 'other'].append(item)
    return groups

def build_tactical_sequences(events):
    usable=sorted([e for e in events if isinstance(e,dict) and event_quality(e)>=3], key=lambda x:int(x.get('startSecond',0)))
    sequences=[]; current=None
    for e in usable:
        mi=e.get('matchIntelligence',{}) or {}; so=e.get('scoreOutcome',{}) or {}
        team=e.get('likelyTeamInPossession') or mi.get('transitionTeam') or mi.get('kickoutTeam') or 'unknown'
        zone=mi.get('fieldZone','unknown'); outcome='unknown'
        if so.get('outcome') not in [None,'unknown']: outcome=so.get('outcome')
        elif mi.get('transitionOutcome') not in [None,'unknown','not_transition']: outcome=mi.get('transitionOutcome')
        elif mi.get('possessionOutcome') not in [None,'unclear']: outcome=mi.get('possessionOutcome')
        elif mi.get('kickoutOutcome') not in [None,'unknown','not_kickout']: outcome=mi.get('kickoutOutcome')
        phase={'time':e.get('time'),'startSecond':int(e.get('startSecond',0)),'endSecond':int(e.get('endSecond',0)),'type':e.get('type'),'team':team,'zone':zone,'outcome':outcome,'summary':e.get('visualAnalysis',''),'clip':e.get('clip')}
        if current and phase['startSecond'] - current['endSecond'] <= 95 and (team == current['likelyTeam'] or team == 'unknown' or current['likelyTeam'] == 'unknown'):
            current['phases'].append(phase); current['endSecond']=max(current['endSecond'],phase['endSecond'])
            if current['likelyTeam']=='unknown' and team!='unknown': current['likelyTeam']=team
            if zone!='unknown': current['zones'].append(zone)
            if outcome!='unknown': current['outcomes'].append(outcome)
        else:
            if current: sequences.append(current)
            current={'sequenceId':len(sequences)+1,'startSecond':phase['startSecond'],'endSecond':phase['endSecond'],'likelyTeam':team,'phases':[phase],'zones':[zone] if zone!='unknown' else [],'outcomes':[outcome] if outcome!='unknown' else []}
    if current: sequences.append(current)
    for s in sequences:
        s['time']=f"{format_timestamp(s['startSecond'])}–{format_timestamp(s['endSecond'])} approx"
        types=[p['type'] for p in s['phases']]
        s['phaseChain']=' → '.join(types[:5])
        s['dominantZone']=max(set(s['zones']), key=s['zones'].count) if s['zones'] else 'unknown'
        s['finalOutcome']=s['outcomes'][-1] if s['outcomes'] else 'unknown'
        s['coachingSummary']=sequence_summary(s)
    return sequences[:12]

def sequence_summary(sequence):
    chain=sequence.get('phaseChain','sequence')
    outcome=sequence.get('finalOutcome','unknown')
    zone=sequence.get('dominantZone','unknown')
    if outcome in ['point','goal','created_score']:
        return f"Positive attacking chain through {zone}; review how the sequence developed into a scoring outcome."
    if outcome in ['wide','save','blocked','created_chance']:
        return f"Chance sequence through {zone}; useful for reviewing shot selection and support around the ball."
    if 'kickout_restart' in chain:
        return f"Restart chain through {zone}; review first and second possession after the kickout."
    if outcome in ['turnover_for','won_back'] or 'turnover' in chain:
        return f"Turnover chain through {zone}; review pressure trigger and next-action decision."
    if 'fast_transition' in chain:
        return f"Transition chain through {zone}; review speed of support and whether the attack stayed direct."
    return f"Tactical sequence through {zone}; review spacing, support and decision-making."

def build_possession_continuity(sequences, facts):
    coached=facts.get('coachedTeam','Team A')
    continuity={'coachedSequences':0,'oppositionSequences':0,'unknownSequences':0,'longestCoachedSpellSeconds':0,'longestOppositionSpellSeconds':0,'possessionNotes':[]}
    for s in sequences:
        duration=max(0,int(s.get('endSecond',0))-int(s.get('startSecond',0)))
        team=s.get('likelyTeam','unknown')
        if team == coached:
            continuity['coachedSequences']+=1; continuity['longestCoachedSpellSeconds']=max(continuity['longestCoachedSpellSeconds'],duration)
        elif team and team!='unknown':
            continuity['oppositionSequences']+=1; continuity['longestOppositionSpellSeconds']=max(continuity['longestOppositionSpellSeconds'],duration)
        else:
            continuity['unknownSequences']+=1
    if continuity['coachedSequences'] > continuity['oppositionSequences']:
        continuity['possessionNotes'].append(f"More classified possession sequences were linked to {coached} than the opposition.")
    elif continuity['oppositionSequences'] > continuity['coachedSequences']:
        continuity['possessionNotes'].append(f"More classified possession sequences were linked to the opposition; check territory and counter-control.")
    else:
        continuity['possessionNotes'].append('Possession ownership remains mixed or unclear from the extracted sequence evidence.')
    return continuity

def build_field_zone_summary(events, sequences):
    zones={z:0 for z in FIELD_ZONES}
    for e in events:
        if not isinstance(e,dict): continue
        z=(e.get('matchIntelligence',{}) or {}).get('fieldZone','unknown')
        zones[z if z in zones else 'unknown']+=1
    sequence_zones={}
    for s in sequences:
        z=s.get('dominantZone','unknown'); sequence_zones[z]=sequence_zones.get(z,0)+1
    top=sorted(sequence_zones.items(), key=lambda x:x[1], reverse=True)[:3]
    return {'eventZoneCounts':zones,'sequenceZoneCounts':sequence_zones,'topSequenceZones':top}

def build_momentum_phases(sequences, facts):
    phases=[]
    if not sequences: return phases
    bucket_seconds=600
    buckets={}
    for s in sequences:
        bucket=int(s.get('startSecond',0))//bucket_seconds
        b=buckets.setdefault(bucket, {'startSecond':bucket*bucket_seconds,'endSecond':bucket*bucket_seconds+bucket_seconds,'positive':0,'negative':0,'scores':0,'chances':0,'turnovers':0,'teams':{}})
        outcome=s.get('finalOutcome','unknown'); team=s.get('likelyTeam','unknown')
        b['teams'][team]=b['teams'].get(team,0)+1
        if outcome in ['point','goal','created_score','created_chance','carried_to_scoring_zone','short_retained','won_clean','won_breaking_ball','turnover_for','won_back']:
            b['positive']+=1
        if outcome in ['wide','save','blocked','lost','turnover_against','turned_over','conceded_counter','lost_clean','lost_breaking_ball','pressed_into_turnover']:
            b['negative']+=1
        if outcome in ['point','goal','created_score']: b['scores']+=1
        if outcome in ['created_chance','wide','save','blocked']: b['chances']+=1
        if outcome in ['turnover_for','turnover_against','won_back','lost','turned_over']: b['turnovers']+=1
    for b in sorted(buckets.values(), key=lambda x:x['startSecond']):
        label='settled_phase'
        if b['scores']>=2: label='scoring_burst'
        elif b['positive']>=3 and b['positive']>b['negative']: label='dominant_spell'
        elif b['negative']>=3 and b['negative']>b['positive']: label='pressure_spell'
        elif b['turnovers']>=2: label='pressure_spell'
        dominant_team=max(b['teams'], key=b['teams'].get) if b['teams'] else 'unknown'
        phases.append({'time':f"{format_timestamp(b['startSecond'])}–{format_timestamp(b['endSecond'])} approx",'label':label,'dominantTeam':dominant_team,'positiveCues':b['positive'],'negativeCues':b['negative'],'scoreCues':b['scores'],'chanceCues':b['chances'],'turnoverCues':b['turnovers']})
    return phases

def aggregate_evidence(events, facts, sequences=None, possession=None, zones=None, momentum=None):
    sequences=sequences or []; possession=possession or {}; zones=zones or {}; momentum=momentum or []
    evidence = {'eventsAnalysed': len([e for e in events if isinstance(e, dict)]),'highValueEvents': 0,'surfacedEvents': 0,'scoresDetected': 0,'widesDetected': 0,'savesDetected': 0,'blockedShotsDetected': 0,'kickoutRetained': 0,'kickoutLost': 0,'kickoutContested': 0,'breakingBallWinsOrContests': 0,'turnoversFor': 0,'turnoversAgainst': 0,'transitionPositive': 0,'transitionNegative': 0,'clipsAvailable': 0,'teamColourConfidence': 'low','sequenceCount': len(sequences),'possessionContinuity': possession,'fieldZoneSummary': zones,'momentumPhases': momentum,'evidenceBullets': [],'coachingTriggers': []}
    for e in events:
        if not isinstance(e, dict): continue
        q = event_quality(e)
        if q >= 3: evidence['surfacedEvents'] += 1
        if q >= 6: evidence['highValueEvents'] += 1
        if e.get('clip'): evidence['clipsAvailable'] += 1
        so = e.get('scoreOutcome', {}) or {}; mi = e.get('matchIntelligence', {}) or {}; tc = e.get('teamColours', {}) or {}
        if tc.get('confidence') in ['medium','high']: evidence['teamColourConfidence'] = tc.get('confidence')
        outcome = so.get('outcome')
        if outcome in ['point','goal']: evidence['scoresDetected'] += 1
        elif outcome == 'wide': evidence['widesDetected'] += 1
        elif outcome == 'save': evidence['savesDetected'] += 1
        elif outcome == 'blocked': evidence['blockedShotsDetected'] += 1
        ko = mi.get('kickoutOutcome')
        if ko in ['short_retained','won_clean','won_breaking_ball']: evidence['kickoutRetained'] += 1
        elif ko in ['lost_clean','lost_breaking_ball','pressed_into_turnover']: evidence['kickoutLost'] += 1
        elif ko == 'contested_unknown': evidence['kickoutContested'] += 1
        if ko in ['won_breaking_ball','lost_breaking_ball','contested_unknown'] or e.get('type') == 'breaking_ball': evidence['breakingBallWinsOrContests'] += 1
        po = mi.get('possessionOutcome')
        if po in ['turnover_for','won_back']: evidence['turnoversFor'] += 1
        elif po in ['turnover_against','lost']: evidence['turnoversAgainst'] += 1
        tr = mi.get('transitionOutcome')
        if tr in ['created_score','created_chance','carried_to_scoring_zone']: evidence['transitionPositive'] += 1
        elif tr in ['slowed_down','forced_backwards','turned_over','conceded_counter']: evidence['transitionNegative'] += 1
    if evidence['sequenceCount']:
        evidence['evidenceBullets'].append(f"Built {evidence['sequenceCount']} tactical sequence(s) from classified review windows.")
    if evidence['kickoutRetained'] > evidence['kickoutLost']:
        evidence['evidenceBullets'].append(f"Kickout platform looked positive in {evidence['kickoutRetained']} classified restart phase(s).")
    elif evidence['kickoutLost'] > evidence['kickoutRetained']:
        evidence['evidenceBullets'].append(f"Kickout/restart pressure showed up in {evidence['kickoutLost']} loss or turnover phase(s).")
        evidence['coachingTriggers'].append('kickout_support')
    if evidence['turnoversFor'] > evidence['turnoversAgainst']:
        evidence['evidenceBullets'].append(f"Middle-third pressure produced {evidence['turnoversFor']} useful turnover cue(s).")
    elif evidence['turnoversAgainst'] > evidence['turnoversFor']:
        evidence['evidenceBullets'].append(f"Possession security needs review: {evidence['turnoversAgainst']} turnover-against cue(s) surfaced.")
        evidence['coachingTriggers'].append('possession_security')
    if evidence['transitionPositive'] > 0:
        evidence['evidenceBullets'].append(f"Transition play created {evidence['transitionPositive']} positive attacking cue(s).")
    if evidence['transitionNegative'] > evidence['transitionPositive']:
        evidence['coachingTriggers'].append('transition_execution')
    if evidence['scoresDetected'] or evidence['widesDetected'] or evidence['savesDetected'] or evidence['blockedShotsDetected']:
        evidence['evidenceBullets'].append(f"Shot-outcome cues: {evidence['scoresDetected']} score(s), {evidence['widesDetected']} wide(s), {evidence['savesDetected']} save(s), {evidence['blockedShotsDetected']} block(s).")
    if facts.get('coachedGoals',0) >= 5:
        evidence['coachingTriggers'].append('protect_goal_threat_strength')
    if not evidence['evidenceBullets']:
        evidence['evidenceBullets'].append('Limited high-confidence sequence evidence surfaced; report should stay conservative and scoreline-led.')
    return evidence

def build_report_prompt(coached, opposition, facts, rules, metadata, events, timeline, sequences, possession_continuity, field_zones, momentum_phases, match_evidence, notes, profile):
    return f'''You are an elite Gaelic football performance analyst working directly for {coached}.
Create a short, sequence-led Gaelic football manager debrief for {coached}. Build conclusions from TACTICAL SEQUENCES, POSSESSION CONTINUITY, FIELD ZONES and MOMENTUM PHASES first, then from scoreline. Do not write generic prose.
MATCH FACTS: {facts}
SCORELINE RULES: {rules}
VIDEO METADATA: {metadata}
TACTICAL SEQUENCES: {sequences}
POSSESSION CONTINUITY: {possession_continuity}
FIELD ZONE SUMMARY: {field_zones}
MOMENTUM PHASES: {momentum_phases}
MATCH EVIDENCE COUNTERS: {match_evidence}
CLASSIFIED EVENTS: {events}
KEY MOMENTS TIMELINE: {timeline}
COACH NOTES: {notes}
PROFILE: {profile}
Rules:
- This is Gaelic football. Use kickouts, breaking ball, middle third, runners from deep, direct ball inside, D protection, counter-press, kick-pass threat, shot selection, game management.
- Do NOT surface repeated unknown outcomes. If an event is unclear, omit it or say evidence was limited.
- Prioritise sequences over isolated moments. A good row should read like: kickout → middle-third contest → direct attack → shot outcome.
- Use field zones: defensive third, middle third, attacking third, scoring zone, central channel, wide channel.
- If {coached} scored {facts['coachedGoals']} goals, treat goal threat as a strength, not a weakness.
- Team colour and possession evidence is approximate; never overclaim ownership if unclear.
- Never contradict final scoreline or invent scorers.
- Reduce waffle. Every row must contain a specific tactical observation or sequence cue.
Return this exact markdown structure:
# {coached} – Match Snapshot
| Item | Detail |
|---|---|
| Scoreline | {facts['scoreline']} |
| Result | {coached} {facts['coachedTeamResult']} by {facts['margin']} point(s) |
| Core Story | One direct sequence-led Gaelic football sentence. |

# {coached} – Evidence Summary
| Evidence Area | What The Analysis Found |
|---|---|
| Review Windows | Use eventsAnalysed, surfacedEvents, sequenceCount and clipsAvailable from MATCH EVIDENCE COUNTERS |
| Possession Continuity | Use POSSESSION CONTINUITY, but avoid false certainty |
| Field Zones | Use FIELD ZONE SUMMARY and top sequence zones |
| Momentum Phases | Use MOMENTUM PHASES if useful; otherwise say no clear swing detected |
| Kickout / Restart | Specific count-led finding from kickoutRetained, kickoutLost, kickoutContested |

# {coached} – Tactical Sequences Worth Reviewing
| Time | Sequence | Zone | Outcome | Coaching Note |
|---|---|---|---|---|
| Use only useful tactical sequences. | phaseChain | dominantZone | finalOutcome | coachingSummary |

# {coached} – Match-Deciding Factor
One blunt Gaelic football paragraph, max 45 words. Tie it to scoreline plus strongest sequence/momentum evidence.

# {coached} – Estimated Key Match Stats
| Metric | {coached} | {opposition} |
|---|---|---|
| Goal Threat | {facts['coachedGoals']} goals + sequence/zone label + ✅/⚠️/❌ | {facts['oppositionGoals']} goals + sequence/zone label + ✅/⚠️/❌ |
| Point Output | {facts['coachedPoints']} points + tactical label + ✅/⚠️/❌ | {facts['oppositionPoints']} points + tactical label + ✅/⚠️/❌ |
| Kickout Platform | count-led restart finding + ✅/⚠️/❌ | count-led restart finding + ✅/⚠️/❌ |
| Breaking Ball | use breaking-ball/kickout cues + ✅/⚠️/❌ | use breaking-ball/kickout cues + ✅/⚠️/❌ |
| Turnover Impact | use turnover counts + ✅/⚠️/❌ | use turnover counts + ✅/⚠️/❌ |
| Transition Threat | use transition counts and sequence evidence + ✅/⚠️/❌ | use transition counts and sequence evidence + ✅/⚠️/❌ |

# {coached} – Key Moments Timeline
| Time | Category | Outcome | Team / Colour Cue | Why It Matters |
|---|---|---|---|---|
| Only include useful classified timeline moments or sequence moments. Do not include rows with all unknowns. | scores/wides/kickouts/turnovers/transitions | outcome | team/colour cue or evidence limited | specific coaching reason |

# {coached} – Main Focus Areas Going Forward
| Priority | Evidence Trigger | Coaching Action |
|---|---|---|
| Specific Gaelic football focus 1 | use sequence/momentum/evidence trigger | practical session action |
| Specific Gaelic football focus 2 | use sequence/momentum/evidence trigger | practical session action |
| Specific Gaelic football focus 3 | use sequence/momentum/evidence trigger | practical session action |

# {coached} – Key Manager Takeaway
One short quote, max 55 words. Must sound like a Gaelic football manager after video review, not a generic AI summary.'''

def generate_analysis(request, job_id=None):
    api_key=os.getenv('OPENAI_API_KEY')
    if not api_key: raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')
    client=OpenAI(api_key=api_key); profile=processing_profile(request.url); facts=build_match_facts(request.matchContext or {})
    set_job_stage(job_id,'metadata','Reading video title, duration and match metadata'); metadata=extract_video_metadata(request.url)
    events=build_event_candidates(request.url, metadata, profile, client, job_id, facts)
    timeline=build_timeline(events)
    sequences=build_tactical_sequences(events)
    possession_continuity=build_possession_continuity(sequences, facts)
    field_zones=build_field_zone_summary(events, sequences)
    momentum_phases=build_momentum_phases(sequences, facts)
    match_evidence=aggregate_evidence(events, facts, sequences, possession_continuity, field_zones, momentum_phases)
    set_job_stage(job_id,'clip_extraction','Review clips created for selected moments')
    coached=facts['coachedTeam']; opposition=facts['teamB'] if facts['teamA']==coached else facts['teamA']
    prompt=build_report_prompt(coached,opposition,facts,build_scoreline_rules(facts),metadata,events,timeline,sequences,possession_continuity,field_zones,momentum_phases,match_evidence,request.notes,profile)
    set_job_stage(job_id,'report','Building sequence-led manager debrief report')
    res=client.chat.completions.create(model='gpt-4o-mini',messages=[{'role':'system','content':'You produce concise sequence-led Gaelic football manager dashboards. You use tactical sequences, possession continuity, field zones and momentum phases before prose and avoid generic analysis.'},{'role':'user','content':prompt}])
    clips=[e.get('clip') for e in events if isinstance(e,dict) and e.get('clip')]
    classifications=[e.get('classification') for e in events if isinstance(e,dict) and e.get('classification')]
    team_colours=[e.get('teamColours') for e in events if isinstance(e,dict) and e.get('teamColours')]
    scoring=[e for e in events if isinstance(e,dict) and e.get('scoreOutcome',{}).get('outcome')!='unknown']
    kickouts=[e for e in events if isinstance(e,dict) and e.get('matchIntelligence',{}).get('kickoutOutcome') not in [None,'not_kickout','unknown']]
    turnovers=[e for e in events if isinstance(e,dict) and e.get('matchIntelligence',{}).get('possessionOutcome') in ['turnover_for','turnover_against','lost','won_back']]
    transitions=[e for e in events if isinstance(e,dict) and e.get('matchIntelligence',{}).get('transitionOutcome') not in [None,'not_transition','unknown']]
    return {'status':'complete','mode':'worker','analysis':res.choices[0].message.content,'videoMetadata':metadata,'matchFacts':facts,'processingProfile':profile['name'],'matchEvidence':match_evidence,'tacticalSequences':sequences,'possessionContinuity':possession_continuity,'fieldZoneSummary':field_zones,'momentumPhases':momentum_phases,'eventCandidates':events,'eventClassifications':classifications,'teamColours':team_colours,'scoringCues':scoring,'kickoutEvents':kickouts,'turnoverEvents':turnovers,'transitionEvents':transitions,'keyMomentsTimeline':timeline,'clips':clips}

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
