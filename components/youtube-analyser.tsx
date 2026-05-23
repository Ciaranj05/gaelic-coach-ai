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
  debug?: any
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
  const managerStats = report?.debug?.managerStatSummary || report?.debug?.matchEvidence?.managerStatSummary || {}
  const tacticalSequences = report?.debug?.tacticalSequences || []

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
    }
  }

  async function handleFileUpload(file: File) {
    setError('')
    setStatus('uploading')
    try {
      const createResponse = await fetch('/api/uploads/create-url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: file.name, contentType: file.type || 'video/mp4', size: file.size }) })
      const uploadData = (await createResponse.json()) as UploadUrlResponse
      await uploadFileToSignedUrl(file, uploadData.uploadUrl, setUploadProgress)
      setUploadedUrl(uploadData.readUrl)
      setUploadedName(file.name)
      setStatus('idle')
    } catch (e) {
      setStatus('error')
      setError('Upload failed.')
    }
  }

  async function analyse() {
    setStatus('processing')
    const response = await fetch('/api/analyse-link', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: analysisUrl, notes, matchContext: { teamA, teamB, coachedTeam, teamAColour, teamBColour, teamAGoals: Number(teamAGoals), teamAPoints: Number(teamAPoints), teamBGoals: Number(teamBGoals), teamBPoints: Number(teamBPoints), competition } }) })
    const data = await response.json()
    setJobId(data.jobId)
    await pollJobUntilComplete(data.jobId)
  }

  return <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-2xl shadow-slate-200/70">
    <p className="text-xl font-bold text-slate-950">Analyse a match</p>

    <div className="mt-6 space-y-4">
      <label className="flex cursor-pointer items-center justify-center rounded-2xl border border-dashed border-emerald-300 bg-white px-4 py-5 text-sm font-bold text-emerald-700">Choose video file<input type="file" accept="video/*" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void handleFileUpload(file) }} /></label>
      <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="Match link" className="w-full rounded-2xl border border-slate-200 px-4 py-4" />
      <div className="grid gap-3 md:grid-cols-2">
        <input value={teamA} onChange={(event) => setTeamA(event.target.value)} placeholder="Team A" className="rounded-2xl border border-slate-200 px-4 py-3" />
        <input value={teamB} onChange={(event) => setTeamB(event.target.value)} placeholder="Team B" className="rounded-2xl border border-slate-200 px-4 py-3" />
      </div>
      <button onClick={analyse} disabled={!requiredFieldsComplete || status === 'processing'} className="w-full rounded-2xl bg-emerald-600 px-6 py-4 font-bold text-white">{status === 'processing' ? 'Analysis running...' : 'Generate AI Match Report'}</button>
    </div>

    {status === 'processing' ? <div className="mt-6 rounded-2xl bg-emerald-50 p-5 text-sm font-medium text-emerald-700"><div className="flex items-center justify-between"><span>{jobDetail || 'Analysis running...'}</span><span>{jobProgress?.percent ?? 5}%</span></div><div className="mt-3 h-3 overflow-hidden rounded-full bg-emerald-100"><div className="h-full rounded-full bg-emerald-600" style={{ width: `${jobProgress?.percent ?? 5}%` }} /></div></div> : null}

    {status === 'complete' && report ? <div className="mt-6 rounded-3xl border border-emerald-100 bg-emerald-50 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-700">Manager Report</p>
          <h3 className="mt-2 text-2xl font-black text-slate-950">{matchTitle}</h3>
          <p className="mt-2 text-sm font-semibold text-slate-600">{report.scoreline}</p>
        </div>
        {jobId ? <a href={`/api/analysis-jobs/${jobId}/download`} className="rounded-2xl bg-slate-950 px-5 py-4 text-sm font-bold text-white">Download Report</a> : null}
      </div>

      <div className="mt-5 rounded-2xl bg-white p-5 shadow-sm">
        <h4 className="font-bold text-slate-950">Executive Summary</h4>
        <p className="mt-3 text-sm leading-7 text-slate-600">{report.summary || report.rawAnalysis}</p>
      </div>

      <div className="mt-5 rounded-2xl bg-white p-5 shadow-sm overflow-x-auto">
        <h4 className="font-bold text-slate-950">Manager Stats</h4>
        <table className="mt-4 w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200">
              <th className="py-2">Stat</th>
              <th className="py-2">Output</th>
              <th className="py-2">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(managerStats).filter(([key]) => key !== 'managerSummary').map(([key, value]: any) => <tr key={key} className="border-b border-slate-100">
              <td className="py-2 font-semibold">{key}</td>
              <td className="py-2">{value?.value || 'Unknown'}</td>
              <td className="py-2">{value?.confidence || 'Low confidence'}</td>
            </tr>)}
          </tbody>
        </table>
      </div>

      {tacticalSequences?.length ? <div className="mt-5 rounded-2xl bg-white p-5 shadow-sm">
        <h4 className="font-bold text-slate-950">Tactical Sequences</h4>
        <div className="mt-4 space-y-3">
          {tacticalSequences.slice(0, 10).map((sequence: any, index: number) => <div key={index} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-400">{sequence.time || 'Sequence'}</p>
            <p className="mt-1 text-sm font-bold text-slate-950">{sequence.phaseChain || sequence.summary || 'Possession sequence review'}</p>
            <p className="mt-1 text-xs text-slate-500">Outcome: {sequence.finalOutcome || 'Unknown'} · Zone: {sequence.dominantZone || 'Unknown'}</p>
          </div>)}
        </div>
      </div> : null}

      {report.timeline?.length ? <div className="mt-5 rounded-3xl bg-white p-5 shadow-sm">
        <h4 className="text-xl font-black text-slate-950">Review Timeline</h4>
        <div className="mt-4 space-y-3">
          {report.timeline.map((item, index) => {
            const playable = canPlayInline(analysisUrl) && item.startSecond !== undefined
            return <div key={`${item.minute}-${index}`} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-400">{item.minute} · {item.category || 'Review'}</p>
                  <p className="mt-1 text-sm font-bold text-slate-950">{item.note}</p>
                </div>
                <button disabled={!playable} onClick={() => setActiveClip(item)} className="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white disabled:bg-slate-300">Watch Clip</button>
              </div>
            </div>
          })}
        </div>
      </div> : null}

      {activeClip && activeClipUrl ? <div className="mt-5 rounded-3xl border border-slate-200 bg-slate-950 p-4 text-white">
        <video key={activeClipUrl} src={activeClipUrl} controls className="w-full rounded-2xl bg-black" />
      </div> : null}
    </div> : null}
  </div>
}
