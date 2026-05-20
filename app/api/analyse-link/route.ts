import { NextResponse } from 'next/server'

type MatchContext = {
  teamA?: string
  teamB?: string
  coachedTeam?: string
  teamAColour?: string
  teamBColour?: string
  teamAGoals?: number
  teamAPoints?: number
  teamBGoals?: number
  teamBPoints?: number
  scoreline?: string
  competition?: string
}

type AnalyseRequest = {
  url?: string
  notes?: string
  matchContext?: MatchContext
}

type CoachingReport = {
  sourceUrl: string
  status: string
  mode: 'ai' | 'demo' | 'worker'
  summary: string
  scoreline: string
  keyInsights: string[]
  trainingFocus: string[]
  timeline: { minute: string; note: string }[]
  nextSteps: string[]
  rawAnalysis?: string
}

function isSupportedUrl(url: string) {
  return url.includes('youtube.com') || url.includes('youtu.be') || url.includes('vimeo.com') || url.includes('veo.co')
}

function formatScore(context?: MatchContext) {
  if (!context?.teamA || !context?.teamB) return context?.scoreline ?? 'Unavailable'

  const aGoals = Number(context.teamAGoals ?? 0)
  const aPoints = Number(context.teamAPoints ?? 0)
  const bGoals = Number(context.teamBGoals ?? 0)
  const bPoints = Number(context.teamBPoints ?? 0)

  return `${context.teamA} ${aGoals}-${aPoints} (${aGoals * 3 + aPoints}) vs ${context.teamB} ${bGoals}-${bPoints} (${bGoals * 3 + bPoints})`
}

function buildDemoReport(url: string, matchContext?: MatchContext): CoachingReport {
  return {
    sourceUrl: url,
    status: 'complete',
    mode: 'demo',
    summary: 'Demo report generated. The Railway worker was not reached, or no analysis input was available.',
    scoreline: formatScore(matchContext),
    keyInsights: [
      'Railway worker was not reached, so this is fallback output.',
      'Check WORKER_API_URL and Railway deployment logs.',
      'Once connected, analysis will use teams, colours, scoreline, transcript and sampled frames.'
    ],
    trainingFocus: [
      'Confirm Railway worker is online.',
      'Confirm OpenAI key is configured in Railway.',
      'Redeploy Vercel after environment variable changes.'
    ],
    timeline: [],
    nextSteps: [
      'Check WORKER_API_URL is set in Vercel.',
      'Check the Railway worker is online.',
      'Redeploy Vercel after setting environment variables.'
    ]
  }
}

function splitAnalysisIntoBullets(text: string) {
  return text
    .split('\n')
    .map((line) => line.replace(/^[-*#\d.\s]+/, '').trim())
    .filter((line) => line.length > 20)
    .slice(0, 8)
}

function weakEvidenceRow(line: string) {
  const lower = line.toLowerCase()

  if (!line.trim().startsWith('|')) return false
  if (lower.includes('|---')) return false
  if (lower.includes('metric') || lower.includes('evidence area') || lower.includes('time') || lower.includes('priority')) return false

  const weakPatterns = [
    'unknown',
    'unclear',
    'not assessed',
    'unassessed',
    'no clear',
    'no defined',
    'no clips',
    'video evidence unavailable',
    '0 transitions',
    '0 transition',
    '0 turnovers',
    'no turnovers recorded',
    'kickouts were not assessed',
    'kickout outcome unclear',
    'possession ownership remains mixed',
    'evidence mainly unknown'
  ]

  return weakPatterns.some((pattern) => lower.includes(pattern))
}

function sanitizeAnalysisMarkdown(markdown: string, matchContext?: MatchContext) {
  const lines = markdown.split('\n')
  const cleaned: string[] = []
  let removedWeakRows = 0

  for (const line of lines) {
    if (weakEvidenceRow(line)) {
      removedWeakRows += 1
      continue
    }
    cleaned.push(line)
  }

  let output = cleaned.join('\n')

  // Remove empty table-only sections that can appear after weak rows are stripped.
  output = output.replace(/# .*?(Evidence Summary|Key Moments Timeline|Tactical Sequences Worth Reviewing)[\s\S]*?\|---.*?\|\s*(?=\n# )/g, (section) => {
    const dataRows = section
      .split('\n')
      .filter((row) => row.trim().startsWith('|') && !row.includes('---'))
      .slice(1)
    return dataRows.length ? section : ''
  })

  if (removedWeakRows > 0) {
    const coached = matchContext?.coachedTeam ?? 'the coached team'
    const fallback = `\n# ${coached} – Evidence Quality Note\nThe video evidence did not support every tactical category with enough confidence, so weak rows such as unknown kickouts, unclear possession and zero-transition claims were removed. The report below focuses on the scoreline, stronger observed moments and coach-confirmed context.\n`
    output = output.replace(/(# .*?– Match-Deciding Factor)/, `${fallback}\n$1`)
  }

  return output
}

async function callRailwayWorker(url: string, notes: string, matchContext?: MatchContext): Promise<CoachingReport | null> {
  const workerUrl = process.env.WORKER_API_URL?.replace(/\/$/, '')

  if (!workerUrl) {
    return null
  }

  const response = await fetch(`${workerUrl}/analyse-video`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, notes, matchContext }),
    cache: 'no-store'
  })

  if (!response.ok) {
    return null
  }

  const data = await response.json()
  const analysis = sanitizeAnalysisMarkdown(String(data.analysis ?? ''), matchContext)
  const bullets = splitAnalysisIntoBullets(analysis)

  return {
    sourceUrl: url,
    status: 'complete',
    mode: 'worker',
    summary: bullets[0] ?? `${matchContext?.coachedTeam ?? 'The coached team'} report generated.`,
    scoreline: formatScore(matchContext),
    keyInsights: bullets.slice(0, 4),
    trainingFocus: bullets.slice(4, 8).length ? bullets.slice(4, 8) : [
      `Review ${matchContext?.coachedTeam ?? 'the coached team'} attacking patterns that created the strongest scoring return.`,
      `Protect defensive shape after attacks, especially if the scoreline shows a strong goal return.`,
      'Use confirmed video moments only when selecting clip-review priorities.'
    ],
    timeline: [],
    nextSteps: ['Use the full report to select three training-ground priorities for the next session.'],
    rawAnalysis: analysis
  }
}

async function generateAiReport(url: string, notes: string, matchContext?: MatchContext): Promise<CoachingReport> {
  const workerReport = await callRailwayWorker(url, notes, matchContext)

  if (workerReport) {
    return workerReport
  }

  const apiKey = process.env.OPENAI_API_KEY

  if (!apiKey || !notes.trim()) {
    return buildDemoReport(url, matchContext)
  }

  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: 'gpt-4o-mini',
      response_format: { type: 'json_object' },
      messages: [
        {
          role: 'system',
          content: 'You are an evidence-first Gaelic football and hurling performance analyst. Return valid JSON only with this exact shape: summary string, scoreline string, keyInsights string array, trainingFocus string array, timeline array of objects with minute and note, nextSteps string array. Use team names throughout. Analyse from the coached team perspective. Avoid generic coaching clichés. Do not invent events. If evidence is weak, state what is uncertain.'
        },
        {
          role: 'user',
          content: `Match context: ${JSON.stringify(matchContext)}\nMatch URL: ${url}\nNotes/transcript/tags:\n${notes}`
        }
      ]
    })
  })

  if (!response.ok) {
    return buildDemoReport(url, matchContext)
  }

  const data = await response.json()
  const content = data.choices?.[0]?.message?.content

  if (!content) {
    return buildDemoReport(url, matchContext)
  }

  const parsed = JSON.parse(content)

  return {
    sourceUrl: url,
    status: 'complete',
    mode: 'ai',
    summary: parsed.summary ?? 'AI report generated.',
    scoreline: parsed.scoreline ?? formatScore(matchContext),
    keyInsights: Array.isArray(parsed.keyInsights) ? parsed.keyInsights : [],
    trainingFocus: Array.isArray(parsed.trainingFocus) ? parsed.trainingFocus : [],
    timeline: Array.isArray(parsed.timeline) ? parsed.timeline : [],
    nextSteps: Array.isArray(parsed.nextSteps) ? parsed.nextSteps : []
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as AnalyseRequest
    const url = body.url?.trim()
    const notes = body.notes?.trim() ?? ''
    const matchContext = body.matchContext

    if (!url) {
      return NextResponse.json({ error: 'Match URL is required.' }, { status: 400 })
    }

    if (!isSupportedUrl(url)) {
      return NextResponse.json(
        { error: 'Please provide a YouTube, Vimeo, or Veo link.' },
        { status: 400 }
      )
    }

    const report = await generateAiReport(url, notes, matchContext)

    return NextResponse.json(report)
  } catch {
    return NextResponse.json(
      { error: 'Unable to analyse this match link.' },
      { status: 500 }
    )
  }
}
