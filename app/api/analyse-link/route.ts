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

type TimelineItem = {
  minute: string
  note: string
  category?: string
  confidence?: string
  reason?: string
  startSecond?: number
  endSecond?: number
}

type CoachingReport = {
  reportId: string
  sourceUrl: string
  status: string
  mode: 'ai' | 'demo' | 'worker'
  summary: string
  scoreline: string
  keyInsights: string[]
  trainingFocus: string[]
  timeline: TimelineItem[]
  nextSteps: string[]
  rawAnalysis?: string
  debug?: Record<string, unknown>
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

function splitAnalysisIntoBullets(text: string) {
  return text
    .split('\n')
    .map((line) => line.replace(/^[-*#\d.\s]+/, '').trim())
    .filter((line) => line.length > 20)
    .slice(0, 8)
}

function humanise(value: unknown) {
  return String(value ?? 'Review moment').replaceAll('_', ' ')
}

function buildTimelineFromWorker(data: Record<string, any>): TimelineItem[] {
  const surfacedClips = data?.matchEvidence?.clipSurface?.priorityClips || data?.debug?.matchEvidence?.clipSurface?.priorityClips || []
  if (Array.isArray(surfacedClips) && surfacedClips.length) {
    return surfacedClips.slice(0, 20).map((clip: any) => ({
      minute: String(clip.time ?? 'N/A'),
      note: String(clip.reason ?? clip.clipLabel ?? 'Review this tactical moment.'),
      category: humanise(clip.category ?? clip.eventType),
      confidence: String(clip.confidence ?? 'estimated'),
      reason: String(clip.clipLabel ?? ''),
      startSecond: Number.isFinite(Number(clip.startSecond)) ? Number(clip.startSecond) : undefined,
      endSecond: Number.isFinite(Number(clip.endSecond)) ? Number(clip.endSecond) : undefined,
    }))
  }

  const events = Array.isArray(data.eventCandidates) ? data.eventCandidates : []
  return events
    .filter((event: any) => event && typeof event === 'object')
    .filter((event: any) => event.classification || ['turnover', 'fast_transition', 'kickout_restart', 'breaking_ball', 'scoring_chance'].includes(String(event.type)))
    .slice(0, 20)
    .map((event: any) => ({
      minute: String(event.time ?? 'N/A'),
      note: String(event.visualAnalysis || event.classification?.coachingReason || event.reason || 'Review this tactical moment.'),
      category: humanise(event.type),
      confidence: String(event.classification?.confidence || event.confidence || 'estimated'),
      reason: String(event.classification?.coachingReason || event.reason || ''),
      startSecond: Number.isFinite(Number(event.startSecond)) ? Number(event.startSecond) : undefined,
      endSecond: Number.isFinite(Number(event.endSecond)) ? Number(event.endSecond) : undefined,
    }))
}

function buildDemoReport(url: string, matchContext?: MatchContext, reportId = randomUUID()): CoachingReport {
  return {
    reportId,
    sourceUrl: url,
    status: 'complete',
    mode: 'demo',
    summary: 'Demo report generated. The Railway worker was not reached, or no analysis input was available.',
    scoreline: formatScore(matchContext),
    keyInsights: ['Railway worker was not reached, so this is fallback output.', 'Check WORKER_API_URL and Railway deployment logs.'],
    trainingFocus: ['Confirm Railway worker is online.', 'Confirm OpenAI key is configured in Railway.'],
    timeline: [],
    nextSteps: ['Check WORKER_API_URL is set in Vercel.', 'Check the Railway worker is online.'],
    debug: { reportId, mode: 'demo', sourceUrl: url, workerReached: false, createdAt: new Date().toISOString() }
  }
}

async function callRailwayWorker(url: string, notes: string, matchContext: MatchContext | undefined, reportId: string): Promise<CoachingReport | null> {
  const workerUrl = process.env.WORKER_API_URL?.replace(/\/$/, '')
  if (!workerUrl) return null

  try {
    const response = await fetch(`${workerUrl}/analyse-video`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, notes, matchContext, reportId }),
      cache: 'no-store'
    })
    if (!response.ok) return null

    const data = await response.json()
    const analysis = String(data.analysis ?? '')
    const bullets = splitAnalysisIntoBullets(analysis)
    const timeline = buildTimelineFromWorker(data)

    return {
      reportId: String(data.reportId ?? reportId),
      sourceUrl: url,
      status: 'complete',
      mode: 'worker',
      summary: bullets[0] ?? `${matchContext?.coachedTeam ?? 'The coached team'} report generated.`,
      scoreline: formatScore(matchContext),
      keyInsights: bullets.slice(0, 4),
      trainingFocus: bullets.slice(4, 8).length ? bullets.slice(4, 8) : [
        `Review ${matchContext?.coachedTeam ?? 'the coached team'} attacking patterns that created the strongest scoring return.`,
        'Protect defensive shape after attacks.',
        'Use the timeline to select clip-review priorities.'
      ],
      timeline,
      nextSteps: ['Use the tactical timeline to review the highest priority moments first.'],
      rawAnalysis: analysis,
      debug: {
        reportId: String(data.reportId ?? reportId),
        mode: 'worker',
        workerReached: true,
        debugReportUrl: data.debugReportUrl,
        latestDebugReportUrl: data.latestDebugReportUrl,
        processingProfile: data.processingProfile,
        videoMetadata: data.videoMetadata,
        matchEvidence: data.matchEvidence,
        managerStatSummary: data.matchEvidence?.managerStatSummary,
        timelineCount: timeline.length,
        eventCandidateCount: Array.isArray(data.eventCandidates) ? data.eventCandidates.length : undefined,
        classificationCount: Array.isArray(data.eventClassifications) ? data.eventClassifications.length : undefined,
        sequenceCount: Array.isArray(data.tacticalSequences) ? data.tacticalSequences.length : undefined,
        clipCount: Array.isArray(data.clips) ? data.clips.length : undefined,
        createdAt: new Date().toISOString()
      }
    }
  } catch {
    return null
  }
}

async function generateAiReport(url: string, notes: string, matchContext?: MatchContext): Promise<CoachingReport> {
  const reportId = randomUUID()
  const workerReport = await callRailwayWorker(url, notes, matchContext, reportId)
  return workerReport || buildDemoReport(url, matchContext, reportId)
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

    const report = await generateAiReport(url, notes, matchContext)
    return NextResponse.json(report)
  } catch {
    return NextResponse.json({ error: 'Unable to analyse this match link.' }, { status: 500 })
  }
}
