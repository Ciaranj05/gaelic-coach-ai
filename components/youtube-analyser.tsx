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
    `Match Analysis`,
    ``,
    `Summary: ${report.summary}`,
    ``,
    `Scoreline: ${report.scoreline}`,
    ``,
    `Key Insights:`,
    ...report.keyInsights.map((item) => `- ${item}`),
    ``,
    `Training Focus:`,
    ...report.trainingFocus.map((item) => `- ${item}`),
    ``,
    `Next Steps:`,
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
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')
  const [report, setReport] = useState<Report | null>(null)

  async function analyse() {
    setError('')
    setReport(null)

    if (!isVideoUrl(url)) {
      setStatus('error')
      setError('Please enter a valid YouTube, Vimeo, or Veo link.')
      return
    }

    setStatus('processing')

    try {
      const response = await fetch('/api/analyse-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, notes })
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

  return (
    <div className="rounded-[2rem] border border-white/10 bg-white/[0.06] p-6 shadow-2xl shadow-green-950/20 backdrop-blur">
      <p className="text-xl font-semibold">Analyse a match link</p>
      <p className="mt-2 text-sm text-zinc-400">
        Paste a YouTube, Vimeo or Veo link. Add match notes for a stronger AI report.
      </p>

      <div className="mt-6 space-y-3">
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://youtube.com/watch?v=..."
          className="w-full rounded-2xl border border-white/10 bg-black/50 px-4 py-4 text-white outline-none placeholder:text-zinc-600 focus:border-green-400/60"
        />

        <textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional: add score, key moments, timestamps, team notes, or copied transcript. Example: 12 mins turnover conceded, 18 mins goal chance, second half kickouts struggled."
          rows={5}
          className="w-full rounded-2xl border border-white/10 bg-black/50 px-4 py-4 text-white outline-none placeholder:text-zinc-600 focus:border-green-400/60"
        />

        <button
          onClick={analyse}
          disabled={!url || status === 'processing'}
          className="w-full rounded-2xl bg-green-400 px-6 py-4 font-semibold text-black transition hover:bg-green-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {status === 'processing' ? 'Generating analysis...' : 'Generate AI Match Report'}
        </button>
      </div>

      {status === 'error' ? (
        <div className="mt-5 rounded-2xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      {status === 'processing' ? (
        <div className="mt-6 rounded-2xl bg-green-400/10 p-5 text-sm text-green-300">
          Calling the analysis API and preparing a structured coaching report...
        </div>
      ) : null}

      {status === 'complete' && report ? (
        <div className="mt-6 space-y-6 rounded-3xl border border-white/10 bg-black/40 p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h3 className="text-2xl font-bold">Match Analysis</h3>
              <p className="mt-1 text-xs uppercase tracking-wide text-green-300">
                {report.mode === 'worker' ? 'Railway AI worker' : report.mode === 'ai' ? 'AI generated' : 'Demo mode'}
              </p>
            </div>

            <button
              onClick={() => downloadReport(report)}
              className="rounded-2xl bg-white px-4 py-3 text-sm font-semibold text-black transition hover:bg-zinc-200"
            >
              Download Report
            </button>
          </div>

          <div className="rounded-2xl bg-white/5 p-4">
            <h4 className="font-semibold text-white">Executive Summary</h4>
            <p className="mt-3 text-sm leading-7 text-zinc-300">{report.summary}</p>
          </div>

          <div>
            <h4 className="font-semibold text-white">Key Insights</h4>
            <ul className="mt-3 space-y-2 text-sm text-zinc-300">
              {report.keyInsights.map((item) => (
                <li key={item} className="rounded-2xl bg-white/5 p-3 leading-6">{item}</li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-white">Training Focus</h4>
            <ul className="mt-3 space-y-2 text-sm text-green-300">
              {report.trainingFocus.map((item) => (
                <li key={item} className="rounded-2xl bg-green-400/10 p-3 leading-6">{item}</li>
              ))}
            </ul>
          </div>

          {report.rawAnalysis ? (
            <div className="rounded-2xl border border-white/10 bg-black/60 p-5">
              <h4 className="font-semibold text-white">Full Coaching Report</h4>
              <pre className="mt-4 max-h-[520px] whitespace-pre-wrap overflow-auto text-sm leading-7 text-zinc-300">
                {report.rawAnalysis}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
