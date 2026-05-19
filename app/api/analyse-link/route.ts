import { NextResponse } from 'next/server'

type AnalyseRequest = {
  url?: string
}

function isSupportedUrl(url: string) {
  return url.includes('youtube.com') || url.includes('youtu.be') || url.includes('vimeo.com') || url.includes('veo.co')
}

function buildDemoReport(url: string) {
  return {
    sourceUrl: url,
    status: 'complete',
    summary: 'This demo report shows the structure coaches will receive once full video processing is connected.',
    scoreline: 'Demo scoreline unavailable until video processing is connected',
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
      'Connect backend video download service.',
      'Extract frames and audio transcript.',
      'Run AI report generation from real match footage.',
      'Store clips and reports against coach accounts.'
    ]
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as AnalyseRequest
    const url = body.url?.trim()

    if (!url) {
      return NextResponse.json({ error: 'Match URL is required.' }, { status: 400 })
    }

    if (!isSupportedUrl(url)) {
      return NextResponse.json(
        { error: 'Please provide a YouTube, Vimeo, or Veo link.' },
        { status: 400 }
      )
    }

    const report = buildDemoReport(url)

    return NextResponse.json(report)
  } catch {
    return NextResponse.json(
      { error: 'Unable to analyse this match link.' },
      { status: 500 }
    )
  }
}
