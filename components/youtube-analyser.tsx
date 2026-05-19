'use client'

import { useState } from 'react'

type Status = 'idle' | 'processing' | 'complete' | 'error'

type Report = {
  mode: 'ai' | 'demo' | 'worker'
  summary: string
  scoreline: string
  keyInsights: string[]
  trainingFocus: string[]
  timeline: { minute: string; note: string }[]
  nextSteps: string[]
  rawAnalysis?: string
}

function isVideoUrl(value: string) {
  return value.includes('youtube.com') || value.includes('youtu.be') || value.includes('vimeo.com') || value.includes('veo.co')
}

function downloadReport(report: Report) {
  const fullReport = report.rawAnalysis || [
    `GAELIC COACH AI - MATCH REPORT`,
    ``,
    `EXECUTIVE SUMMARY`,
    report.summary,
    ``,
    `SCORELINE`,
    report.scoreline,
    ``,
    `KEY TACTICAL THEMES`,
    ...report.keyInsights.map((item) => `- ${item}`),
    ``,
    `TRAINING PRIORITIES`,
    ...report.trainingFocus.map((item) => `- ${item}`),
    ``,
    `COACH ACTIONS`,
    ...report.nextSteps.map((item) => `- ${item}`)
  ].join('\n')

  const blob = new Blob([fullReport], { type: 'text/plain;charset=utf-8' })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = 'gaelic-coach-ai-match-report.txt'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(href)
}

export default function YouTubeAnalyser() {
  const [url, setUrl] = useState('')
  const [teamA, setTeamA] = useState('')
  const [teamB, setTeamB] = useState('')
  const [coachedTeam, setCoachedTeam] = useState('')
  const [teamAColour, setTeamAColour] = useState('')
  const [teamBColour, setTeamBColour] = useState('')
  const [scoreline, setScoreline] = useState('')
  const [competition, setCompetition] = useState('')
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')
  const [report, setReport] = useState<Report | null>(null)

  const requiredFieldsComplete = Boolean(
    url && teamA && teamB && coachedTeam && teamAColour && teamBColour && scoreline
  )

  async function analyse() {
    setError('')
    setReport(null)

    if (!isVideoUrl(url)) {
      setStatus('error')
      setError('Please enter a valid YouTube, Vimeo, or Veo link.')
      return
    }

    if (!requiredFieldsComplete) {
      setStatus('error')
      setError('Please complete the required match context: teams, coached team, colours and scoreline.')
      return
    }

    setStatus('processing')

    const matchContext = {
      teamA,
      teamB,
      coachedTeam,
      teamAColour,
      teamBColour,
      scoreline,
      competition
    }

    try {
      const response = await fetch('/api/analyse-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, notes, matchContext })
      })

      const data = await response.json()

      if (!response.ok) {
        setStatus('error')
        setError(data.error ?? 'Unable to analyse this link.')
        return
      }

      setReport(data)
      setStatus('complete')
    } catch {
      setStatus('error')
      setError('Unable to connect to the analysis service.')
    }
  }

  const tacticalThemes = report?.keyInsights.slice(0, 4) ?? []
  const trainingPriorities = report?.trainingFocus.slice(0, 4) ?? []
  const coachActions = report?.nextSteps.slice(0, 3) ?? []

  return (
    <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-2xl shadow-slate-200/70">
      <p className="text-xl font-bold text-slate-950">Analyse a match link</p>
      <p className="mt-2 text-sm text-slate-500">
        Add the match context first so the AI can produce a more specific, trustworthy coaching report.
      </p>

      <div className="mt-6 space-y-4">
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="YouTube, Vimeo or Veo match link"
          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
        />

        <div className="grid gap-3 md:grid-cols-2">
          <input
            value={teamA}
            onChange={(event) => setTeamA(event.target.value)}
            placeholder="Team A name *"
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
          />
          <input
            value={teamB}
            onChange={(event) => setTeamB(event.target.value)}
            placeholder="Team B name *"
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
          />
          <input
            value={teamAColour}
            onChange={(event) => setTeamAColour(event.target.value)}
            placeholder="Team A colours *"
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
          />
          <input
            value={teamBColour}
            onChange={(event) => setTeamBColour(event.target.value)}
            placeholder="Team B colours *"
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
          />
        </div>

        <select
          value={coachedTeam}
          onChange={(event) => setCoachedTeam(event.target.value)}
          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
        >
          <option value="">Which team are you coaching? *</option>
          {teamA ? <option value={teamA}>{teamA}</option> : null}
          {teamB ? <option value={teamB}>{teamB}</option> : null}
        </select>

        <div className="grid gap-3 md:grid-cols-2">
          <input
            value={scoreline}
            onChange={(event) => setScoreline(event.target.value)}
            placeholder="Final scoreline * e.g. Team A 1-12, Team B 1-15"
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
          />
          <input
            value={competition}
            onChange={(event) => setCompetition(event.target.value)}
            placeholder="Competition / match type"
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
          />
        </div>

        <textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional coach notes: key moments, timestamps, tactical focus, injuries, conditions, or areas you want reviewed."
          rows={4}
          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
        />

        <button
          onClick={analyse}
          disabled={!requiredFieldsComplete || status === 'processing'}
          className="w-full rounded-2xl bg-emerald-600 px-6 py-4 font-bold text-white shadow-lg shadow-emerald-600/20 transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {status === 'processing' ? 'Generating analysis...' : 'Generate AI Match Report'}
        </button>

        <p className="text-center text-xs text-slate-500">
          Required: teams, colours, coached team and scoreline. This improves report accuracy and reduces generic AI output.
        </p>
      </div>

      {status === 'error' ? (
        <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">
          {error}
        </div>
      ) : null}

      {status === 'processing' ? (
        <div className="mt-6 rounded-2xl bg-emerald-50 p-5 text-sm font-medium text-emerald-700">
          Analysing match context, transcript, sampled frames and coaching inputs...
        </div>
      ) : null}

      {status === 'complete' && report ? (
        <div className="mt-6 space-y-6 rounded-3xl border border-slate-200 bg-slate-50 p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h3 className="text-2xl font-bold text-slate-950">Match Report</h3>
              <p className="mt-1 text-xs uppercase tracking-wide text-emerald-600">
                {report.mode === 'worker' ? 'Railway AI worker' : report.mode === 'ai' ? 'AI generated' : 'Demo mode'}
              </p>
            </div>

            <button
              onClick={() => downloadReport(report)}
              className="rounded-2xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Download Full Report
            </button>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl bg-white p-4 shadow-sm">
              <p className="text-xs uppercase tracking-wide text-slate-500">Scoreline</p>
              <p className="mt-2 text-sm font-semibold text-slate-950">{report.scoreline}</p>
            </div>
            <div className="rounded-2xl bg-white p-4 shadow-sm">
              <p className="text-xs uppercase tracking-wide text-slate-500">Insights</p>
              <p className="mt-2 text-sm font-semibold text-slate-950">{report.keyInsights.length} themes found</p>
            </div>
            <div className="rounded-2xl bg-white p-4 shadow-sm">
              <p className="text-xs uppercase tracking-wide text-slate-500">Training</p>
              <p className="mt-2 text-sm font-semibold text-slate-950">{report.trainingFocus.length} priorities</p>
            </div>
          </div>

          <div className="rounded-2xl bg-white p-5 shadow-sm">
            <h4 className="text-lg font-semibold text-slate-950">Executive Summary</h4>
            <p className="mt-3 text-sm leading-7 text-slate-600">{report.summary}</p>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h4 className="font-semibold text-slate-950">Key Tactical Themes</h4>
              <ul className="mt-4 space-y-3 text-sm text-slate-600">
                {tacticalThemes.map((item, index) => (
                  <li key={item} className="rounded-2xl bg-slate-50 p-4 leading-6">
                    <span className="mr-2 font-bold text-emerald-600">{index + 1}.</span>{item}
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-5 shadow-sm">
              <h4 className="font-semibold text-slate-950">Training Priorities</h4>
              <ul className="mt-4 space-y-3 text-sm text-emerald-800">
                {trainingPriorities.map((item, index) => (
                  <li key={item} className="rounded-2xl bg-white/70 p-4 leading-6">
                    <span className="mr-2 font-bold text-emerald-600">{index + 1}.</span>{item}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {coachActions.length ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h4 className="font-semibold text-slate-950">Recommended Coach Actions</h4>
              <ul className="mt-4 grid gap-3 text-sm text-slate-600 md:grid-cols-3">
                {coachActions.map((item) => (
                  <li key={item} className="rounded-2xl bg-slate-50 p-4 leading-6">{item}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {report.rawAnalysis ? (
            <details className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <summary className="cursor-pointer font-semibold text-slate-950">
                View Full Coaching Report
              </summary>
              <pre className="mt-4 max-h-[520px] whitespace-pre-wrap overflow-auto text-sm leading-7 text-slate-600">
                {report.rawAnalysis}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
