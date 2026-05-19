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

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function cleanMarkdown(value: string) {
  return value.replace(/\*\*(.*?)\*\*/g, '$1').replace(/^[-*]\s+/, '').trim()
}

function sectionMeta(title: string) {
  const lower = title.toLowerCase()
  if (lower.includes('dashboard') || lower.includes('snapshot')) return { label: 'Overview', icon: '🏁', accent: 'emerald' }
  if (lower.includes('takeaway')) return { label: 'Coach Insight', icon: '💡', accent: 'indigo' }
  if (lower.includes('comparison')) return { label: 'Team Comparison', icon: '📊', accent: 'blue' }
  if (lower.includes('moment')) return { label: 'Review Timeline', icon: '⏱️', accent: 'blue' }
  if (lower.includes('strength')) return { label: 'Positive Themes', icon: '✅', accent: 'emerald' }
  if (lower.includes('issue') || lower.includes('risk') || lower.includes('fix')) return { label: 'Priority Fixes', icon: '⚠️', accent: 'amber' }
  if (lower.includes('training')) return { label: 'Session Plan', icon: '🏋️', accent: 'emerald' }
  if (lower.includes('confidence')) return { label: 'Evidence Quality', icon: '🔎', accent: 'slate' }
  return { label: 'Analysis', icon: '•', accent: 'slate' }
}

function isTableLine(line: string) {
  return line.startsWith('|') && line.endsWith('|')
}

function isSeparatorLine(line: string) {
  return /^\|?[\s:-]+(\|[\s:-]+)+\|?$/.test(line)
}

function parseTableRow(line: string) {
  return line
    .split('|')
    .slice(1, -1)
    .map((cell) => cleanMarkdown(cell.trim()))
}

function renderMarkdownTable(rows: string[]) {
  const cleanRows = rows.filter((row) => !isSeparatorLine(row))
  if (cleanRows.length < 2) return ''

  const headers = parseTableRow(cleanRows[0])
  const bodyRows = cleanRows.slice(1).map(parseTableRow).filter((row) => row.some(Boolean))

  return `<div class="table-wrap"><table class="analysis-table"><thead><tr>${headers
    .map((header) => `<th>${escapeHtml(header)}</th>`)
    .join('')}</tr></thead><tbody>${bodyRows
    .map((row) => `<tr>${headers.map((_, index) => `<td>${escapeHtml(row[index] ?? '')}</td>`).join('')}</tr>`)
    .join('')}</tbody></table></div>`
}

function renderSectionBody(lines: string[]) {
  const html: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (isTableLine(line)) {
      const tableLines: string[] = []
      while (index < lines.length && isTableLine(lines[index])) {
        tableLines.push(lines[index])
        index += 1
      }
      html.push(renderMarkdownTable(tableLines))
      continue
    }

    const numbered = line.match(/^\d+\.\s+(.*)$/)
    if (numbered) {
      const cleaned = cleanMarkdown(numbered[1])
      const [title, ...rest] = cleaned.split(':')
      const detail = rest.join(':').trim()
      html.push(`<div class="insight-row"><strong>${escapeHtml(title)}</strong>${detail ? `<span>${escapeHtml(detail)}</span>` : ''}</div>`)
      index += 1
      continue
    }

    const bullet = line.match(/^[-*]\s+(.*)$/)
    if (bullet) {
      html.push(`<div class="insight-row"><span>${escapeHtml(cleanMarkdown(bullet[1]))}</span></div>`)
      index += 1
      continue
    }

    html.push(`<p>${escapeHtml(cleanMarkdown(line))}</p>`)
    index += 1
  }

  return html.join('')
}

function renderPremiumAnalysis(markdown: string) {
  const lines = markdown.split('\n').map((line) => line.trim()).filter(Boolean)
  const sections: { title: string; body: string[] }[] = []
  let current: { title: string; body: string[] } | null = null

  for (const line of lines) {
    if (line.startsWith('# ')) {
      if (current) sections.push(current)
      current = { title: cleanMarkdown(line.replace(/^#\s+/, '')), body: [] }
    } else if (current) {
      current.body.push(line)
    } else {
      current = { title: 'Match Dashboard', body: [line] }
    }
  }

  if (current) sections.push(current)

  return sections.map((section) => {
    const meta = sectionMeta(section.title)
    return `<section class="report-section ${meta.accent}">
      <div class="section-heading">
        <div class="section-icon">${meta.icon}</div>
        <div>
          <div class="section-label">${meta.label}</div>
          <h2>${escapeHtml(section.title)}</h2>
        </div>
      </div>
      <div class="section-body">${renderSectionBody(section.body)}</div>
    </section>`
  }).join('')
}

function downloadReport(report: Report, matchTitle: string) {
  const fullReport = report.rawAnalysis || [
    `# Match Dashboard`,
    report.summary,
    ``,
    `# Tactical Comparison`,
    ...report.keyInsights.map((item) => `- ${item}`),
    ``,
    `# Training Priorities`,
    ...report.trainingFocus.map((item) => `- ${item}`),
    ``,
    `# Coach Actions`,
    ...report.nextSteps.map((item) => `- ${item}`)
  ].join('\n')

  const htmlReport = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(matchTitle)} - Gaelic Coach AI Report</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; background: #f4f7f6; color: #0f172a; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    .page { max-width: 1080px; margin: 32px auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 28px; overflow: hidden; box-shadow: 0 28px 80px rgba(15,23,42,.12); }
    .hero { background: linear-gradient(135deg,#061826,#065f46); color: white; padding: 42px 46px; }
    .brand { display:flex; align-items:center; gap:12px; }
    .logo { width:44px; height:44px; border-radius:14px; background:#10b981; display:flex; align-items:center; justify-content:center; font-weight:900; }
    .eyebrow { color: #a7f3d0; font-size: 12px; text-transform: uppercase; letter-spacing: .22em; font-weight: 800; }
    h1 { margin: 22px 0 0; font-size: 40px; line-height: 1.05; letter-spacing: -.04em; }
    .meta { margin-top: 14px; color: #d1fae5; font-size: 15px; font-weight: 650; }
    .content { padding: 34px 40px 44px; }
    .grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 14px; margin-bottom: 22px; }
    .stat { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 18px; padding: 18px; }
    .label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .16em; font-weight: 900; }
    .value { margin-top: 8px; font-size: 16px; font-weight: 850; color:#0f172a; }
    .report-section { margin-top: 18px; border: 1px solid #e2e8f0; border-radius: 22px; background: #fff; overflow: hidden; }
    .report-section.emerald { border-color: #bbf7d0; }
    .report-section.amber { border-color: #fde68a; }
    .report-section.blue { border-color: #bfdbfe; }
    .report-section.indigo { border-color: #c7d2fe; }
    .section-heading { display:flex; gap:13px; align-items:center; padding: 18px 20px; border-bottom: 1px solid #e2e8f0; background:#fbfdff; }
    .section-icon { width:38px; height:38px; border-radius:12px; background:#0f172a; color:white; display:flex; align-items:center; justify-content:center; font-size:17px; }
    .section-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .2em; font-weight: 900; }
    h2 { margin: 3px 0 0; font-size: 22px; line-height: 1.15; letter-spacing: -.03em; }
    .section-body { padding: 18px 20px 20px; }
    p { margin: 0 0 12px; color: #334155; line-height: 1.65; font-size: 14px; }
    .table-wrap { width: 100%; overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 16px; background: #fff; }
    .analysis-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .analysis-table th { background: #f1f5f9; color: #334155; text-align: left; padding: 13px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; border-bottom: 1px solid #e2e8f0; }
    .analysis-table td { padding: 14px; border-bottom: 1px solid #eef2f7; color: #334155; line-height: 1.5; vertical-align: top; }
    .analysis-table tr:last-child td { border-bottom: 0; }
    .analysis-table td:first-child { font-weight: 800; color: #0f172a; width: 24%; }
    .insight-row { border: 1px solid #e2e8f0; background: #f8fafc; border-radius: 14px; padding: 13px 14px; margin: 8px 0; color:#334155; line-height:1.55; font-size: 14px; }
    .insight-row strong { display:block; color:#0f172a; margin-bottom: 4px; }
    .insight-row span { color:#475569; }
    .footer { border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 28px; color: #64748b; font-size: 12px; }
    @media print { body { background: white; } .page { margin: 0; box-shadow: none; border-radius: 0; } }
    @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } .content { padding: 22px; } .hero { padding: 32px 24px; } }
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div class="brand"><div class="logo">GC</div><div><div class="eyebrow">Gaelic Coach AI</div><div>Premium Tactical Dashboard</div></div></div>
      <h1>${escapeHtml(matchTitle)}</h1>
      <div class="meta">AI-assisted tactical report • ${escapeHtml(report.scoreline)}</div>
    </div>
    <div class="content">
      <div class="grid">
        <div class="stat"><div class="label">Scoreline</div><div class="value">${escapeHtml(report.scoreline)}</div></div>
        <div class="stat"><div class="label">Format</div><div class="value">Comparison dashboard</div></div>
        <div class="stat"><div class="label">Output</div><div class="value">Coach actions</div></div>
      </div>
      ${renderPremiumAnalysis(fullReport)}
      <div class="footer">Generated by Gaelic Coach AI. This report should support, not replace, coach judgement and video review.</div>
    </div>
  </div>
</body>
</html>`

  const blob = new Blob([htmlReport], { type: 'text/html;charset=utf-8' })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = 'gaelic-coach-ai-premium-match-report.html'
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
  const [teamAGoals, setTeamAGoals] = useState('')
  const [teamAPoints, setTeamAPoints] = useState('')
  const [teamBGoals, setTeamBGoals] = useState('')
  const [teamBPoints, setTeamBPoints] = useState('')
  const [competition, setCompetition] = useState('')
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')
  const [report, setReport] = useState<Report | null>(null)

  const scoreComplete = teamAGoals !== '' && teamAPoints !== '' && teamBGoals !== '' && teamBPoints !== ''
  const requiredFieldsComplete = Boolean(url && teamA && teamB && coachedTeam && teamAColour && teamBColour && scoreComplete)
  const matchTitle = `${teamA || 'Team A'} vs ${teamB || 'Team B'}`

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
      setError('Please complete the required match context: teams, coached team, colours and goals/points for both teams.')
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

  return (
    <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-2xl shadow-slate-200/70">
      <p className="text-xl font-bold text-slate-950">Analyse a match link</p>
      <p className="mt-2 text-sm text-slate-500">Add match context first. The full report is downloaded separately so the page stays clean.</p>

      <div className="mt-6 space-y-4">
        <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="YouTube, Vimeo or Veo match link" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        <div className="grid gap-3 md:grid-cols-2">
          <input value={teamA} onChange={(event) => setTeamA(event.target.value)} placeholder="Team A name *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
          <input value={teamB} onChange={(event) => setTeamB(event.target.value)} placeholder="Team B name *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
          <input value={teamAColour} onChange={(event) => setTeamAColour(event.target.value)} placeholder="Team A colours *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
          <input value={teamBColour} onChange={(event) => setTeamBColour(event.target.value)} placeholder="Team B colours *" className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        </div>
        <select value={coachedTeam} onChange={(event) => setCoachedTeam(event.target.value)} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100">
          <option value="">Which team are you coaching? *</option>
          {teamA ? <option value={teamA}>{teamA}</option> : null}
          {teamB ? <option value={teamB}>{teamB}</option> : null}
        </select>
        <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-sm font-bold text-slate-950">Final Score</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl bg-white p-3 shadow-sm"><p className="mb-2 text-xs font-semibold text-slate-500">{teamA || 'Team A'}</p><div className="grid grid-cols-2 gap-2"><input type="number" min="0" value={teamAGoals} onChange={(event) => setTeamAGoals(event.target.value)} placeholder="Goals" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /><input type="number" min="0" value={teamAPoints} onChange={(event) => setTeamAPoints(event.target.value)} placeholder="Points" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /></div></div>
            <div className="rounded-2xl bg-white p-3 shadow-sm"><p className="mb-2 text-xs font-semibold text-slate-500">{teamB || 'Team B'}</p><div className="grid grid-cols-2 gap-2"><input type="number" min="0" value={teamBGoals} onChange={(event) => setTeamBGoals(event.target.value)} placeholder="Goals" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /><input type="number" min="0" value={teamBPoints} onChange={(event) => setTeamBPoints(event.target.value)} placeholder="Points" className="rounded-xl border border-slate-200 px-3 py-2 text-slate-950 outline-none" /></div></div>
          </div>
        </div>
        <input value={competition} onChange={(event) => setCompetition(event.target.value)} placeholder="Competition / match type" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Optional coach notes: key moments, timestamps, tactical focus, injuries, conditions, or areas you want reviewed." rows={4} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-slate-950 outline-none placeholder:text-slate-400 focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100" />
        <button onClick={analyse} disabled={!requiredFieldsComplete || status === 'processing'} className="w-full rounded-2xl bg-emerald-600 px-6 py-4 font-bold text-white shadow-lg shadow-emerald-600/20 transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40">{status === 'processing' ? 'Generating analysis...' : 'Generate AI Match Report'}</button>
        <p className="text-center text-xs text-slate-500">Required: teams, colours, coached team and structured goals/points score.</p>
      </div>

      {status === 'error' ? <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">{error}</div> : null}
      {status === 'processing' ? <div className="mt-6 rounded-2xl bg-emerald-50 p-5 text-sm font-medium text-emerald-700">Analysing match context, transcript, sampled frames and coaching inputs...</div> : null}
      {status === 'complete' && report ? (
        <div className="mt-6 rounded-3xl border border-emerald-100 bg-emerald-50 p-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-700">Report Ready</p><h3 className="mt-2 text-2xl font-black text-slate-950">{matchTitle}</h3><p className="mt-2 text-sm font-semibold text-slate-600">{report.scoreline}</p></div><button onClick={() => downloadReport(report, matchTitle)} className="rounded-2xl bg-slate-950 px-5 py-4 text-sm font-bold text-white shadow-lg shadow-slate-900/20 transition hover:bg-slate-800">Download Premium Report</button></div><div className="mt-5 rounded-2xl bg-white p-5 shadow-sm"><h4 className="font-bold text-slate-950">Quick Summary</h4><p className="mt-3 line-clamp-4 text-sm leading-7 text-slate-600">{report.summary}</p></div><p className="mt-4 text-xs text-slate-500">The detailed tactical breakdown is kept inside the downloadable report to keep the workspace clean.</p></div>
      ) : null}
    </div>
  )
}
