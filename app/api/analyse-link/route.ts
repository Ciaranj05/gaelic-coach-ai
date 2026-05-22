import { NextResponse } from 'next/server'
import { randomUUID } from 'crypto'

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
  sourceType?: string
}

type AnalyseRequest = {
  url?: string
  notes?: string
  matchContext?: MatchContext
}

function isSupportedUrl(url: string) {
  return (
    url.includes('youtube.com') ||
    url.includes('youtu.be') ||
    url.includes('vimeo.com') ||
    url.includes('veo.co') ||
    url.includes('drive.google.com') ||
    url.includes('storage.googleapis.com') ||
    url.includes('googleapis.com')
  )
}

function formatScore(context?: MatchContext) {
  if (!context?.teamA || !context?.teamB) return context?.scoreline ?? 'Unavailable'
  const aGoals = Number(context.teamAGoals ?? 0)
  const aPoints = Number(context.teamAPoints ?? 0)
  const bGoals = Number(context.teamBGoals ?? 0)
  const bPoints = Number(context.teamBPoints ?? 0)
  return `${context.teamA} ${aGoals}-${aPoints} (${aGoals * 3 + aPoints}) vs ${context.teamB} ${bGoals}-${bPoints} (${bGoals * 3 + bPoints})`
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as AnalyseRequest
    const url = body.url?.trim()
    const notes = body.notes?.trim() ?? ''
    const matchContext = body.matchContext

    if (!url) return NextResponse.json({ error: 'Match URL is required.' }, { status: 400 })

    if (!isSupportedUrl(url)) {
      return NextResponse.json({ error: 'Please provide a YouTube, Vimeo, Veo, Google Drive, or uploaded video link.' }, { status: 400 })
    }

    const workerUrl = process.env.WORKER_API_URL?.replace(/\/$/, '')

    if (!workerUrl) {
      return NextResponse.json({ error: 'WORKER_API_URL is not configured.' }, { status: 500 })
    }

    const reportId = randomUUID()

    const response = await fetch(`${workerUrl}/analysis-jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url,
        notes,
        matchContext,
        reportId,
      }),
      cache: 'no-store'
    })

    const data = await response.json()

    if (!response.ok) {
      return NextResponse.json({
        error: 'Unable to start analysis job.',
        detail: data
      }, { status: 502 })
    }

    return NextResponse.json({
      status: 'processing',
      mode: 'job',
      reportId,
      jobId: data.jobId,
      progress: data.progress,
      scoreline: formatScore(matchContext),
      message: 'Analysis started successfully.'
    })
  } catch {
    return NextResponse.json({ error: 'Unable to start analysis job.' }, { status: 500 })
  }
}
