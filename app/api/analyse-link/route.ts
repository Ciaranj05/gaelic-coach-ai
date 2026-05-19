import { NextResponse } from 'next/server'

type AnalyseRequest = {
  url?: string
  notes?: string
}

type CoachingReport = {
  sourceUrl: string
  status: string
  mode: 'ai' | 'demo'
  summary: string
  scoreline: string
  keyInsights: string[]
  trainingFocus: string[]
  timeline: { minute: string; note: string }[]
  nextSteps: string[]
}

function isSupportedUrl(url: string) {
  return url.includes('youtube.com') || url.includes('youtu.be') || url.includes('vimeo.com') || url.includes('veo.co')
}

function buildDemoReport(url: string): CoachingReport {
  return {
    sourceUrl: url,
    status: 'complete',
    mode: 'demo',
    summary: 'Demo report generated. Add an OpenAI API key and match notes/transcript to generate tailored coaching analysis.',
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
    timeline: [
      { minute: '0-15', note: 'Opening phase: establish defensive structure and kickout options.' },
      { minute: '16-30', note: 'Middle phase: review turnovers and support running.' },
      { minute: '31-45', note: 'Momentum phase: assess scoring chances and shot selection.' },
      { minute: '46-60+', note: 'Closing phase: review energy, shape, and game management.' }
    ],
    nextSteps: [
      'Add OPENAI_API_KEY in Vercel environment variables.',
      'Provide match notes, transcript, or tagged moments for tailored analysis.',
      'Connect background video processing for frame/audio extraction.',
      'Store reports against coach and team accounts.'
    ]
  }
}

async function generateAiReport(url: string, notes: string): Promise<CoachingReport> {
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
