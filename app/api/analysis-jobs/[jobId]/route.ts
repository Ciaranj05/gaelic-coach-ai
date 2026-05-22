import { NextResponse } from 'next/server'

type TimelineItem = {
  minute: string
  note: string
  category?: string
  confidence?: string
  reason?: string
  startSecond?: number
  endSecond?: number
}

function humanise(value: unknown) {
  return String(value ?? 'Review moment').replaceAll('_', ' ')
}

function splitAnalysisIntoBullets(text: string) {
  return text
    .split('\n')
    .map((line) => line.replace(/^[-*#\d.\s]+/, '').trim())
    .filter((line) => line.length > 20)
    .slice(0, 8)
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

function normaliseCompletedJob(job: Record<string, any>) {
  const result = job.result || {}
  const analysis = String(result.analysis ?? '')
  const bullets = splitAnalysisIntoBullets(analysis)
  const timeline = buildTimelineFromWorker(result)

  return {
    status: 'complete',
    mode: 'worker',
    jobId: job.jobId,
    reportId: result.reportId || job.jobId,
    summary: bullets[0] || 'Report generated successfully.',
    scoreline: result.matchFacts?.scoreline || 'Unavailable',
    keyInsights: bullets.slice(0, 4),
    trainingFocus: bullets.slice(4, 8),
    timeline,
    nextSteps: ['Use the tactical timeline to review the highest priority moments first.'],
    rawAnalysis: analysis,
    debug: {
      progress: job.progress,
      stage: job.stage,
      detail: job.detail,
      matchEvidence: result.matchEvidence,
      managerStatSummary: result.matchEvidence?.managerStatSummary,
      timelineCount: timeline.length,
      debugReportUrl: result.debugReportUrl,
      latestDebugReportUrl: result.latestDebugReportUrl,
    }
  }
}

export async function GET(_request: Request, context: { params: { jobId: string } }) {
  try {
    const workerUrl = process.env.WORKER_API_URL?.replace(/\/$/, '')
    if (!workerUrl) return NextResponse.json({ error: 'WORKER_API_URL is not configured.' }, { status: 500 })

    const response = await fetch(`${workerUrl}/analysis-jobs/${context.params.jobId}`, { cache: 'no-store' })
    const job = await response.json()

    if (!response.ok) {
      return NextResponse.json(job, { status: response.status })
    }

    if (job.status === 'complete' && job.result) {
      return NextResponse.json(normaliseCompletedJob(job))
    }

    if (job.status === 'failed') {
      return NextResponse.json({
        status: 'error',
        jobId: job.jobId,
        error: job.error || 'Analysis failed.',
        progress: job.progress,
        detail: job.detail,
        stage: job.stage,
      }, { status: 500 })
    }

    return NextResponse.json({
      status: 'processing',
      jobId: job.jobId,
      progress: job.progress,
      detail: job.detail,
      stage: job.stage,
      updatedAt: job.updatedAt,
    })
  } catch {
    return NextResponse.json({ error: 'Unable to poll analysis job.' }, { status: 500 })
  }
}
