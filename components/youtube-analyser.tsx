'use client'

import { useState } from 'react'

type Status = 'idle' | 'uploading' | 'processing' | 'complete' | 'error'

type TimelineItem = {
  minute?: string
  note?: string
  category?: string
  confidence?: string
  reason?: string
  startSecond?: number
  endSecond?: number
}

type Report = {
  status?: string
  mode?: string
  summary?: string
  scoreline?: string
  keyInsights?: string[]
  trainingFocus?: string[]
  timeline?: TimelineItem[]
  rawAnalysis?: string
}

type UploadUrlResponse = {
  uploadUrl?: string
  readUrl?: string
  error?: string
}

function isSupportedUrl(value: string) {
  return /youtube\.com|youtu\.be|vimeo\.com|veo\.co|drive\.google\.com|storage\.googleapis\.com|googleapis\.com/i.test(value)
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function downloadReport(report: Report, title: string) {
  const content = [
    `# ${title}`,
    `Score: ${report.scoreline || 'Unavailable'}`,
    '',
    '## Summary',
    report.summary || '',
    '',
    '## Tactical Timeline',
    ...(report.timeline || []).map((item) => `- ${item.minute || 'N/A'} | ${item.category || 'Review'} | ${item.note || item.reason || ''}`),
    '',
    '## Training Focus',
    ...(report.trainingFocus || []).map((item) => `- ${item}`),
    '',
    report.rawAnalysis || '',
  ].join('\n')

  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'gaelic-coach-ai-match-report.md'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function uploadFile(file: File, uploadUrl: string, onProgress: (value: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', uploadUrl)
    xhr.setRequestHeader('Content-Type', file.type || 'video/mp4')
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed with status ${xhr.status}`))
    xhr.onerror = () => reject(new Error('Upload failed. Please check your connection.'))
    xhr.send(file)
  })
}

export default function YouTubeAnalyser() {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')
  const [url, setUrl] = useState('')
  const [uploadedUrl, setUploadedUrl] = useState('')
  const [uploadedName, setUploadedName] = useState('')
  const [uploadProgress, setUploadProgress] = useState(0)
  const [jobProgress, setJobProgress] = useState(0)
  const [jobMessage, setJobMessage] = useState('')
  const [jobId, setJobId] = useState('')
  const [report, setReport] = useState<Report | null>(null)

  const [teamA, setTeamA] = useState('')
  const [teamB, setTeamB] = useState('')
  const [teamAColour, setTeamAColour] = useState('')
  const [teamBColour, setTeamBColour] = useState('')
  const [coachedTeam, setCoachedTeam] = useState('')
  const [teamAGoals, setTeamAGoals] = useState('')
  const [teamAPoints, setTeamAPoints] = useState('')
  const [teamBGoals, setTeamBGoals] = useState('')
  const [teamBPoints, setTeamBPoints] = useState('')
  const [competition, setCompetition] = useState('')
  const [notes, setNotes] = useState('')

  const analysisUrl = uploadedUrl || url.trim()
  const matchTitle = `${teamA || 'Team A'} vs ${teamB || 'Team B'}`
  const ready = Boolean(analysisUrl && teamA && teamB && coachedTeam && teamAColour && teamBColour && teamAGoals !== '' && teamAPoints !== '' && teamBGoals !== '' && teamBPoints !== '')

  async function handleUpload(file: File) {
    setError('')
    setReport(null)
    setUploadedName(file.name)
    setUploadProgress(0)
    setStatus('uploading')

    if (file.size > 3 * 1024 * 1024 * 1024) {
      setStatus('error')
      setError('Maximum upload size is 3GB.')
      return
    }

    try {
      const response = await fetch('/api/uploads/create-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, contentType: file.type || 'video/mp4', size: file.size }),
      })
      const data = await response.json() as UploadUrlResponse
      if (!response.ok || !data.uploadUrl || !data.readUrl) throw new Error(data.error || 'Unable to create upload URL.')
      await uploadFile(file, data.uploadUrl, setUploadProgress)
      setUploadedUrl(data.readUrl)
      setUrl('')
      setStatus('idle')
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : 'Upload failed.')
    }
  }

  async function pollJob(nextJobId: string) {
    for (let attempt = 0; attempt < 720; attempt += 1) {
      await wait(5000)
      const response = await fetch(`/api/analysis-jobs/${nextJobId}`, { cache: 'no-store' })
      const data = await response.json()

      if (!response.ok) {
        setStatus('error')
        setError(data.error || 'Analysis failed.')
        return
      }

      if (data.progress?.percent) setJobProgress(data.progress.percent)
      if (data.progress?.label || data.detail) setJobMessage(data.progress?.label || data.detail)

      if (data.status === 'complete') {
        setReport(data)
        setStatus('complete')
        return
      }
    }

    setStatus('error')
    setError('Analysis is still running. Please check Railway logs or try again later.')
  }

  async function analyse() {
    setError('')
    setReport(null)
    setJobId('')
    setJobProgress(5)
    setJobMessage('Starting analysis...')

    if (!uploadedUrl && !isSupportedUrl(url)) {
      setStatus('error')
      setError('Please upload a video or paste a supported YouTube, Vimeo, Veo, Google Drive, or uploaded video link.')
      return
    }

    if (!ready) {
      setStatus('error')
      setError('Please complete video/link, teams, colours, coached team, and final score.')
      return
    }

    setStatus('processing')

    const matchContext = {
      teamA,
      teamB,
      coachedTeam,
      teamAColour,
      teamBColour,
      teamAGoals: Number(teamAGoals),
      teamAPoints: Number(teamAPoints),
      teamBGoals: Number(teamBGoals),
      teamBPoints: Number(teamBPoints),
      competition,
      sourceType: uploadedUrl ? 'uploaded_video' : 'link',
    }

    try {
      const response = await fetch('/api/analyse-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: analysisUrl, notes, matchContext }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error || 'Unable to start analysis.')

      if (data.jobId) {
        setJobId(data.jobId)
        setJobProgress(data.progress?.percent || 5)
        setJobMessage(data.message || 'Analysis started.')
        await pollJob(data.jobId)
        return
      }

      setReport(data)
      setStatus('complete')
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : 'Unable to connect to the analysis service.')
    }
  }

  return (
    <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-2xl shadow-slate-200/70">
      <p className="text-xl font-bold text-slate-950">Analyse a match</p>
      <p className="mt-2 text-sm text-slate-500">Upload a video file or paste a match link. Add the basic match context and the report will appear here when ready.</p>

      <div className="mt-6 space-y-4">
        <div className="rounded-3xl border border-emerald-100 bg-emerald-50 p-4">
          <p className="text-sm font-bold text-slate-950">Upload Match Video</p>
          <p className="mt-1 text-xs text-slate-600">Supports large files up to 3GB.</p>
          <label className="mt-4 flex cursor-pointer items-center justify-center rounded-2xl border border-dashed border-emerald-300 bg-white px-4 py-5 text-sm font-bold text-emerald-700 hover:bg-emerald-50">
            Choose video file
            <input type="file" accept="video/*,.mp4,.mov,.m4v,.avi,.mkv" className="hidden" onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void handleUpload(file)
              event.currentTarget.value = ''
            }} />
          </label>
          {status === 'uploading' ? <div className="mt-4"><div className="flex justify-between text-xs font-semibold text-slate-600"><span>{uploadedName}</span><span>{uploadProgress}%</span></div><div className="mt-2 h-3 overflow-hidden rounded-full bg-emerald-100"><div className="h-full rounded-full bg-emerald-600" style={{ width: `${uploadProgress}%` }} /></div></div> : null}
          {uploadedUrl ? <div className="mt-4 rounded-2xl bg-white p-3 text-xs font-semibold text-emerald-700">Uploaded: {uploadedName || 'video file'}. Ready to analyse.</div> : null}
        </div>

        <div className="flex items-center gap-3 text-xs font-bold uppercase tracking-[0.2em] text-slate-400"><div className="h-px flex-1 bg-slate-200" />or paste a link<div className="h-px flex-1 bg-slate-200" /></div>
        <input value={url} onChange={(event) => { setUrl(event.target.value); if (event.target.value) setUploadedUrl('') }} placeholder="YouTube, Vimeo, Veo, Google Drive, or uploaded video link" className="w-full rounded-2xl border border-slate-200 px-4 py-4 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />

        <div className="grid gap-3 md:grid-cols-2">
          <input value={teamA} onChange={(event) => setTeamA(event.target.value)} placeholder="Team A name *" className="rounded-2xl border border-slate-200 px-4 py-3 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
          <input value={teamB} onChange={(event) => setTeamB(event.target.value)} placeholder="Team B name *" className="rounded-2xl border border-slate-200 px-4 py-3 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
          <input value={teamAColour} onChange={(event) => setTeamAColour(event.target.value)} placeholder="Team A colours *" className="rounded-2xl border border-slate-200 px-4 py-3 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
          <input value={teamBColour} onChange={(event) => setTeamBColour(event.target.value)} placeholder="Team B colours *" className="rounded-2xl border border-slate-200 px-4 py-3 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        </div>

        <select value={coachedTeam} onChange={(event) => setCoachedTeam(event.target.value)} className="w-full rounded-2xl border border-slate-200 px-4 py-4 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100">
          <option value="">Which team are you coaching? *</option>
          {teamA ? <option value={teamA}>{teamA}</option> : null}
          {teamB ? <option value={teamB}>{teamB}</option> : null}
        </select>

        <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-sm font-bold text-slate-950">Final Score</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl bg-white p-3 shadow-sm">
              <p className="mb-2 text-xs font-semibold text-slate-500">{teamA || 'Team A'}</p>
              <div className="grid grid-cols-2 gap-2">
                <input type="number" min="0" value={teamAGoals} onChange={(event) => setTeamAGoals(event.target.value)} placeholder="Goals" className="rounded-xl border border-slate-200 px-3 py-2 outline-none" />
                <input type="number" min="0" value={teamAPoints} onChange={(event) => setTeamAPoints(event.target.value)} placeholder="Points" className="rounded-xl border border-slate-200 px-3 py-2 outline-none" />
              </div>
            </div>
            <div className="rounded-2xl bg-white p-3 shadow-sm">
              <p className="mb-2 text-xs font-semibold text-slate-500">{teamB || 'Team B'}</p>
              <div className="grid grid-cols-2 gap-2">
                <input type="number" min="0" value={teamBGoals} onChange={(event) => setTeamBGoals(event.target.value)} placeholder="Goals" className="rounded-xl border border-slate-200 px-3 py-2 outline-none" />
                <input type="number" min="0" value={teamBPoints} onChange={(event) => setTeamBPoints(event.target.value)} placeholder="Points" className="rounded-xl border border-slate-200 px-3 py-2 outline-none" />
              </div>
            </div>
          </div>
        </div>

        <input value={competition} onChange={(event) => setCompetition(event.target.value)} placeholder="Competition / match type" className="w-full rounded-2xl border border-slate-200 px-4 py-3 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Optional coach notes, key moments, tactical focus or areas you want reviewed." rows={4} className="w-full rounded-2xl border border-slate-200 px-4 py-4 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />

        <button onClick={analyse} disabled={!ready || status === 'uploading' || status === 'processing'} className="w-full rounded-2xl bg-emerald-600 px-6 py-4 font-bold text-white shadow-lg shadow-emerald-600/20 hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40">
          {status === 'uploading' ? 'Uploading video...' : status === 'processing' ? 'Analysis running...' : 'Generate AI Match Report'}
        </button>
        <p className="text-center text-xs text-slate-500">Required: upload/link, teams, colours, coached team and final score.</p>
      </div>

      {status === 'error' ? <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">{error}</div> : null}

      {status === 'processing' ? <div className="mt-6 rounded-2xl bg-emerald-50 p-5 text-sm font-medium text-emerald-700"><div className="flex items-center justify-between gap-3"><span>{jobMessage || 'Analysis running...'}</span><span>{jobProgress || 5}%</span></div><div className="mt-3 h-3 overflow-hidden rounded-full bg-emerald-100"><div className="h-full rounded-full bg-emerald-600" style={{ width: `${jobProgress || 5}%` }} /></div>{jobId ? <p className="mt-3 text-xs">Job ID: {jobId}. Keep this page open and the report will appear automatically.</p> : null}</div> : null}

      {status === 'complete' && report ? <div className="mt-6 rounded-3xl border border-emerald-100 bg-emerald-50 p-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-700">Report Ready</p><h3 className="mt-2 text-2xl font-black text-slate-950">{matchTitle}</h3><p className="mt-2 text-sm font-semibold text-slate-600">{report.scoreline}</p></div><button onClick={() => downloadReport(report, matchTitle)} className="rounded-2xl bg-slate-950 px-5 py-4 text-sm font-bold text-white shadow-lg shadow-slate-900/20 hover:bg-slate-800">Download Report</button></div><div className="mt-5 rounded-2xl bg-white p-5 shadow-sm"><h4 className="font-bold text-slate-950">Quick Summary</h4><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-600">{report.summary || report.rawAnalysis || 'Report generated.'}</p></div>{report.timeline?.length ? <div className="mt-5 rounded-3xl bg-white p-5 shadow-sm"><h4 className="text-xl font-black text-slate-950">Tactical Timeline</h4><div className="mt-4 space-y-3">{report.timeline.map((item, index) => <div key={index} className="rounded-2xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-400">{item.minute || 'N/A'} · {item.category || 'Review'}</p><p className="mt-1 text-sm font-bold text-slate-950">{item.note || item.reason}</p></div>)}</div></div> : null}</div> : null}
    </div>
  )
}
