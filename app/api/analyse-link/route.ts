import { NextResponse } from 'next/server'

type AnalyseRequest = {
  url?: string
  notes?: string
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

function buildDemoReport(url: string): CoachingReport {
  return {
    sourceUrl: url,
    status: 'complete',
    mode: 'demo',
    summary: 'Demo report generated. The Railway worker was not reached, or no analysis input was available.',
    scoreline: 'Unavailable until match data is provided',
    keyInsights: [
      'Kickout retention and second-ball response should be reviewed.',
      'Transition defence is a priority after turnovers in the middle third.',
      'Attacking shape is strongest when support runners arrive from deep.',
      'Shot selection should be reviewed from wide angles and under pressure.'
    ],
    trainingFocus: [
      'Kickout exit patterns under pressure',
      'Transition defence recovery runs',
      'Support play after turnovers won',
      'Decision-making in the scoring zone'
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
    .slice(0, 6)
}

async function callRailwayWorker(url: string, notes: string): Promise<CoachingReport | null> {
  const workerUrl = process.env.WORKER_API_URL?.replace(/\/$/, '')

  if (!workerUrl) {
    return null
  }

  const response = await fetch(`${workerUrl}/analyse-video`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, notes }),
    cache: 'no-store'
  })

  if (!response.ok) {
    return null
  }

  const data = await response.json()
  const analysis = String(data.analysis ?? '')
  const bullets = splitAnalysisIntoBullets(analysis)

  return {
    sourceUrl: url,
    status: 'complete',
    mode: 'worker',
    summary: bullets[0] ?? 'Railway worker generated a coaching report.',
    scoreline: 'Provided in coach notes if available',
    keyInsights: bullets.slice(0, 4),
    trainingFocus: bullets.slice(4, 8).length ? bullets.slice(4, 8) : [
      'Review kickout strategy and retention under pressure.',
      'Work on transition defence after turnovers.',
      'Improve decision-making and shot selection in scoring zones.'
    ],
    timeline: [],
    nextSteps: ['Next step: connect real YouTube download, transcript extraction and frame analysis.'],
    rawAnalysis: analysis
  }
}

async function generateAiReport(url: string, notes: string): Promise<CoachingReport> {
  const workerReport = await callRailwayWorker(url, notes)

  if (workerReport) {
    return workerReport
  }

  const apiKey = process.env.OPENAI_API_KEY

  if (!apiKey || !notes.trim()) {
    return buildDemoReport(url)
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
          content: 'You are an expert Gaelic football and hurling performance analyst. Return valid JSON only with this exact shape: summary string, scoreline string, keyInsights string array, trainingFocus string array, timeline array of objects with minute and note, nextSteps string array. Be practical, coach-focused, and avoid claiming to see video unless details are present in the notes.'
        },
        {
          role: 'user',
          content: `Analyse this match context for a Gaelic coach. Match URL: ${url}\n\nAvailable notes, transcript or tagged moments:\n${notes}`
        }
      ]
    })
  })

  if (!response.ok) {
    return buildDemoReport(url)
  }

  const data = await response.json()
  const content = data.choices?.[0]?.message?.content

  if (!content) {
    return buildDemoReport(url)
  }

  const parsed = JSON.parse(content)

  return {
    sourceUrl: url,
    status: 'complete',
    mode: 'ai',
    summary: parsed.summary ?? 'AI report generated.',
    scoreline: parsed.scoreline ?? 'Not provided',
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

    if (!url) {
      return NextResponse.json({ error: 'Match URL is required.' }, { status: 400 })
    }

    if (!isSupportedUrl(url)) {
      return NextResponse.json(
        { error: 'Please provide a YouTube, Vimeo, or Veo link.' },
        { status: 400 }
      )
    }

    const report = await generateAiReport(url, notes)

    return NextResponse.json(report)
  } catch {
    return NextResponse.json(
      { error: 'Unable to analyse this match link.' },
      { status: 500 }
    )
  }
}
