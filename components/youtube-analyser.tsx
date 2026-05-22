'use client'

import { useState } from 'react'

type Status = 'idle' | 'uploading' | 'processing' | 'complete' | 'error'

type TimelineItem = {
  minute: string
  note: string
  category?: string
  confidence?: string
  reason?: string
  startSecond?: number
  endSecond?: number
}

type Report = {
  mode: string
  summary: string
  scoreline: string
  keyInsights: string[]
  trainingFocus: string[]
  timeline: TimelineItem[]
  nextSteps: string[]
  rawAnalysis?: string
}

type UploadUrlResponse = {
  uploadUrl: string
  readUrl: string
  gsUri: string
  objectName: string
  error?: string
}

type JobProgress = { percent?: number; label?: string }

function isVideoUrl(value: string) {
  return value.includes('youtube.com') || value.includes('youtu.be') || value.includes('vimeo.com') || value.includes('veo.co') || value.includes('drive.google.com') || value.includes('storage.googleapis.com') || value.includes('googleapis.com')
}

function canPlayInline(value: string) {
  return value.includes('storage.googleapis.com') || value.includes('googleapis.com') || value.match(/\.(mp4|mov)(\?|$)/i)
}

function clipUrl(sourceUrl: string, item: TimelineItem) {
  if (!sourceUrl || item.startSecond === undefined) return ''
  const end = item.endSecond ?? item.startSecond + 30
  return `${sourceUrl}#t=${Math.max(0, item.startSecond)},${end}`
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function downloadReport(report: Report, matchTitle: string) {
  const lines = [`# ${matchTitle}`, `Score: ${report.scoreline}`, '', '## Summary', report.summary, '', '## Tactical Timeline', ...(report.timeline || []).map((item) => `- ${item.minute} | ${item.category || 'Review'} | ${item.note}`), '', '## Training Focus', ...report.trainingFocus.map((item) => `- ${item}`), '', report.rawAnalysis || ''].join('\n')
  const blob = new Blob([lines], { type: 'text/markdown;charset=utf-8' })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = 'gaelic-coach-ai-match-report.md'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(href)
}

function uploadFileToSignedUrl(file: File, uploadUrl: string, onProgress: (progress: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', uploadUrl)
    xhr.setRequestHeader('Content-Type', file.type || 'video/mp4')
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed with status ${xhr.status}`))
    xhr.onerror = () => reject(new Error('Upload failed. Please check your connection and try again.'))
    xhr.send(file)
  })
}

export default function YouTubeAnalyser() {
  const [url, setUrl] = useState('')
  const [uploadedUrl, setUploadedUrl] = useState('')
  const [uploadedName, setUploadedName] = useState('')
  const [uploadProgress, setUploadProgress] = useState(0)
  const [teamA, setTeamA] = useState('')
  const [teamB, setTeamB] = useState('')
  const [coachedTeam, setCoachedTeam] = useState('')
  const [teamAColour, setTeamAColour] = useState('')
  const [teamBColour, setTeamBColour] = useState('')
  const [teamAGoals, setTeamAGoals] = useState('')
  const [teamAPoints, setTeamAPoints] = useState('')
  const [teamBGoals, setTeamBGoals] = useState('')
  const [teamBPoints, setTeamBPoints] = useState('')
  const [competition, setCompetition] = useState('')
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')
  const [report, setReport] = useState<Report | null>(null)
  const [activeClip, setActiveClip] = useState<TimelineItem | null>(null)
  const [jobId, setJobId] = useState('')
  const [jobProgress, setJobProgress] = useState<JobProgress | null>(null)
  const [jobDetail, setJobDetail] = useState('')

  const analysisUrl = uploadedUrl || url
  const scoreComplete = teamAGoals !== '' && teamAPoints !== '' && teamBGoals !== '' && teamBPoints !== ''
  const requiredFieldsComplete = Boolean(analysisUrl && teamA && teamB && coachedTeam && teamAColour && teamBColour && scoreComplete)
  const matchTitle = `${teamA || 'Team A'} vs ${teamB || 'Team B'}`
  const activeClipUrl = activeClip ? clipUrl(analysisUrl, activeClip) : ''

  async function pollJobUntilComplete(nextJobId: string) {
    for (let attempt = 0; attempt < 720; attempt += 1) {
      await wait(5000)
      const response = await fetch(`/api/analysis-jobs/${nextJobId}`, { cache: 'no-store' })
      const data = await response.json()
      if (!response.ok) {
        setStatus('error')
        setError(data.error || 'Analysis failed while polling the report.')
        return
      }
      if (data.progress) setJobProgress(data.progress)
      if (data.detail) setJobDetail(data.detail)
      if (data.status === 'complete') {
        setReport(data)
        setStatus('complete')
        setJobDetail('Report ready')
        return
      }
      if (data.status === 'error' || data.status === 'failed') {
        setStatus('error')
        setError(data.error || 'Analysis failed.')
        return
      }
    }
    setStatus('error')
    setError('Analysis is still running after a long wait. Please check Railway logs or try refreshing later.')
  }

  async function handleFileUpload(file: File) {
    setError('')
    setReport(null)
    setActiveClip(null)
    setJobId('')
    setJobProgress(null)
    setJobDetail('')
    setUploadedUrl('')
    setUploadedName(file.name)
    setUploadProgress(0)
    setStatus('uploading')
    if (!file.type.startsWith('video/') && !file.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/)) {
      setStatus('error')
      setError('Please choose a video file.')
      return
    }
    if (file.size > 3 * 1024 * 1024 * 1024) {
      setStatus('error')
      setError('Maximum supported upload size is 3GB.')
      return
    }
    try {
      const createResponse = await fetch('/api/uploads/create-url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: file.name, contentType: file.type || 'video/mp4', size: file.size }) })
      const uploadData = (await createResponse.json()) as UploadUrlResponse
      if (!createResponse.ok || !uploadData.uploadUrl || !uploadData.readUrl) throw new Error(uploadData.error || 'Unable to create upload URL.')
      await uploadFileToSignedUrl(file, uploadData.uploadUrl, setUploadProgress)
      setUploadedUrl(uploadData.readUrl)
      setUrl('')
      setStatus('idle')
    } catch (uploadError) {
      setStatus('error')
      setError(uploadError instanceof Error ? uploadError.message : 'Upload failed.')
    }
  }

  async function analyse() {
    setError('')
    setReport(null)
    setActiveClip(null)
    setJobId('')
    setJobProgress(null)
    setJobDetail('Starting analysis job...')
    if (!uploadedUrl && !isVideoUrl(url)) {
      setStatus('error')
      setError('Please enter a valid YouTube, Vimeo, Veo, Google Drive link, or upload a video file.')
      return
    }
    if (!requiredFieldsComplete) {
      setStatus('error')
      setError('Please complete the required match context: teams, coached team, colours and goals/points for both teams.')
      return
    }
    setStatus('processing')
    const matchContext = { teamA, teamB, coachedTeam, teamAColour, teamBColour, teamAGoals: Number(teamAGoals), teamAPoints: Number(teamAPoints), teamBGoals: Number(teamBGoals), teamBPoints: Number(teamBPoints), competition, sourceType: uploadedUrl ? 'uploaded_video' : 'link' }
    try {
      const response = await fetch('/api/analyse-link', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: analysisUrl, notes, matchContext }) })
      const data = await response.json()
      if (!response.ok) {
        setStatus('error')
        setError(data.error ?? 'Unable to start this analysis.')
        return
      }
      if (data.jobId) {
        setJobId(data.jobId)
        setJobProgress(data.progress || { percent: 5, label: 'Queued for analysis' })
        setJobDetail(data.message || 'Analysis started. Waiting for Railway worker...')
        await pollJobUntilComplete(data.jobId)
        return
      }
      setReport(data)
      setStatus('complete')
    } catch {
      setStatus('error')
      setError('Unable to connect to the analysis service.')
    }
  }

  return (
    <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-2xl shadow-slate-200/70">
      <p className="text-xl font-bold text-slate-950">Analyse a match</p>
      <p className="mt-2 text-sm text-slate-500">Upload a video file or paste a match link. Reports now stay on the page while the long-running Railway analysis completes.</p>
      <div className="mt-6 space-y-4">
        <div className="rounded-3xl border border-emerald-100 bg-emerald-50 p-4">
          <p className="text-sm font-bold text-slate-950">Upload Match Video</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">Supports large video files up to 3GB. Upload goes directly to secure cloud storage.</p>
          <label className="mt-4 flex cursor-pointer items-center justify-center rounded-2xl border border-dashed border-emerald-300 bg-white px-4 py-5 text-sm font-bold text-emerald-700 transition hover:bg-emerald-50">Choose video file<input type="file" accept="video/*,.mp4,.mov,.avi,.mkv" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void handleFileUpload(file); event.currentTarget.value = '' }} /></label>
          {status === 'uploading' ? <div className="mt-4"><div className="flex justify-between text-xs font-semibold text-slate-600"><span>{uploadedName || 'Uploading video'}</span><span>{uploadProgress}%</span></div><div className="mt-2 h-3 overflow-hidden rounded-full bg-emerald-100"><div className="h-full rounded-full bg-emerald-600 transition-all" style={{ width: `${uploadProgress}%` }} /></div></div> : null}
          {uploadedUrl ? <div className="mt-4 rounded-2xl bg-white p-3 text-xs font-semibold text-emerald-700">Uploaded: {uploadedName || 'video file'}. Ready to analyse.</div> : null}
        </div>
        <div className="flex items-center gap-3 text-xs font-bold uppercase tracking-[0.2em] text-slate-400"><div className="h-px flex-1 bg-slate-200" />or paste a link<div className="h-px flex-1 bg-slate-200" /></div>
        <input value={url} onChange={(event) => { setUrl(event.target.value); if (event.target.value) setUploadedUrl('') }} placeholder="YouTube, Vimeo, Veo or Google Drive match link" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        <div className="grid gap-3 md:grid-cols-2"><input value={teamA} onChange={(event) => setTeamA(event.target.value)} placeholder="Team A name *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" /><input value={teamB} onChange={(event) => setTeamB(event.target.value)} placeholder="Team B name *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" /><input value={teamAColour} onChange={(event) => setTeamAColour(event.target.value)} placeholder="Team A colours *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" /><input value={teamBColour} onChange={(event) => setTeamBColour(event.target.value)} placeholder="Team B colours *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" /></div>
        <select value={coachedTeam} onChange={(event) => setCoachedTeam(event.target.value)} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"><option value="">Which team are you coaching? *</option>{teamA ? <option value={teamA}>{teamA}</option> : null}{teamB ? <option value={teamB}>{teamB}</option> : null}</select>
        <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-bold text-slate-950">Final Score</p><div className="mt-3 grid gap-3 md:grid-cols-2"><div className="rounded-2xl bg-white p-3 shadow-sm"><p className="mb-2 text-xs font-semibold text-slate-500">{teamA || 'Team A'}</p><div className="grid grid-cols-2 gap-2"><input type="number" min="0" value={teamAGoals} onChange={(event) => setTeamAGoals(event.target.value)} placeholder="Goals" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /><input type="number" min="0" value={teamAPoints} onChange={(event) => setTeamAPoints(event.target.value)} placeholder="Points" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /></div></div><div className="rounded-2xl bg-white p-3 shadow-sm"><p className="mb-2 text-xs font-semibold text-slate-500">{teamB || 'Team B'}</p><div className="grid grid-cols-2 gap-2"><input type="number" min="0" value={teamBGoals} onChange={(event) => setTeamBGoals(event.target.value)} placeholder="Goals" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /><input type="number" min="0" value={teamBPoints} onChange={(event) => setTeamBPoints(event.target.value)} placeholder="Points" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /></div></div></div></div>
        <input value={competition} onChange={(event) => setCompetition(event.target.value)} placeholder="Competition / match type" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Optional coach notes: key moments, timestamps, tactical focus, injuries, conditions, or areas you want reviewed." rows={4} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        <button onClick={analyse} disabled={!requiredFieldsComplete || status === 'processing' || status === 'uploading'} className="w-full rounded-2xl bg-emerald-600 px-6 py-4 font-bold text-white shadow-lg shadow-emerald-600/20 transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40">{status === 'processing' ? 'Analysis running...' : status === 'uploading' ? 'Uploading video...' : 'Generate AI Match Report'}</button>
      </div>
      {status === 'error' ? <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">{error}</div> : null}
      {status === 'processing' ? <div className="mt-6 rounded-2xl bg-emerald-50 p-5 text-sm font-medium text-emerald-700"><div className="flex items-center justify-between gap-3"><span>{jobDetail || jobProgress?.label || 'Analysis running...'}</span><span>{jobProgress?.percent ?? 5}%</span></div><div className="mt-3 h-3 overflow-hidden rounded-full bg-emerald-100"><div className="h-full rounded-full bg-emerald-600 transition-all" style={{ width: `${jobProgress?.percent ?? 5}%` }} /></div>{jobId ? <p className="mt-3 text-xs text-emerald-700">Job ID: {jobId}. Keep this page open and the report will appear automatically.</p> : null}</div> : null}
      {status === 'complete' && report ? <div className="mt-6 rounded-3xl border border-emerald-100 bg-emerald-50 p-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-700">Report Ready</p><h3 className="mt-2 text-2xl font-black text-slate-950">{matchTitle}</h3><p className="mt-2 text-sm font-semibold text-slate-600">{report.scoreline}</p></div><button onClick={() => downloadReport(report, matchTitle)} className="rounded-2xl bg-slate-950 px-5 py-4 text-sm font-bold text-white shadow-lg shadow-slate-900/20 transition hover:bg-slate-800">Download Report</button></div><div className="mt-5 rounded-2xl bg-white p-5 shadow-sm"><h4 className="font-bold text-slate-950">Quick Summary</h4><p className="mt-3 text-sm leading-7 text-slate-600">{report.summary}</p></div>{report.timeline?.length ? <div className="mt-5 rounded-3xl bg-white p-5 shadow-sm"><div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-700">Tactical Timeline</p><h4 className="mt-1 text-xl font-black text-slate-950">Priority review moments</h4></div><p className="text-xs font-semibold text-slate-500">{report.timeline.length} moments surfaced</p></div><div className="mt-4 space-y-3">{report.timeline.map((item, index) => { const playable = canPlayInline(analysisUrl) && item.startSecond !== undefined; return <div key={`${item.minute}-${index}`} className="rounded-2xl border border-slate-200 bg-slate-50 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-400">{item.minute} · {item.category || 'Review'}</p><p className="mt-1 text-sm font-bold text-slate-950">{item.note}</p>{item.reason ? <p className="mt-1 text-xs text-slate-500">{item.reason}</p> : null}</div><div className="flex items-center gap-2"><span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-500">{item.confidence || 'estimated'}</span><button disabled={!playable} onClick={() => setActiveClip(item)} className="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:bg-slate-300">Watch Clip</button></div></div></div> })}</div>{!canPlayInline(analysisUrl) ? <p className="mt-4 rounded-2xl bg-amber-50 p-3 text-xs font-semibold text-amber-700">Inline clip playback is available for uploaded MP4 files. Link-only sources still show timestamps for manual review.</p> : null}</div> : null}{activeClip && activeClipUrl ? <div className="mt-5 rounded-3xl border border-slate-200 bg-slate-950 p-4 text-white"><div className="mb-3 flex items-center justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-300">Now Playing</p><p className="text-sm font-bold">{activeClip.category || 'Review'} · {activeClip.minute}</p></div><button onClick={() => setActiveClip(null)} className="rounded-xl bg-white/10 px-3 py-2 text-xs font-bold">Close</button></div><video key={activeClipUrl} src={activeClipUrl} controls className="w-full rounded-2xl bg-black" /></div> : null}</div> : null}
    </div>
  )
}
