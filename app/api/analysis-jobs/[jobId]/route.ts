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

function isFallbackText(value: unknown) {
  const text = String(value ?? '').toLowerCase()
  return text.includes('fallback tactical checkpoint') || text.includes('dense fallback tactical checkpoint') || text.includes('video metadata/download scanning was unavailable')
}

function hasRealAnalysedEvents(data: Record<string, any>) {
  const events = Array.isArray(data?.eventCandidates) ? data.eventCandidates : []
  const realEvents = events.filter((event: any) => {
    if (!event || typeof event !== 'object') return false
    if (isFallbackText(event.reason) || isFallbackText(event.visualAnalysis)) return false
    return Boolean(event.classification || event.matchIntelligence || event.scoreOutcome || event.kickoutVisual || event.framesAnalysed)
  })

  const evidenceEvents = Number(data?.matchEvidence?.eventsAnalysed ?? 0)
  const classifications = Array.isArray(data?.eventClassifications) ? data.eventClassifications.length : 0
  const sequences = Array.isArray(data?.tacticalSequences) ? data.tacticalSequences.length : 0
  const clips = Array.isArray(data?.clips) ? data.clips.length : 0

  return realEvents.length > 0 || evidenceEvents > 0 || classifications > 0 || sequences > 0 || clips > 0
}

function hasFallbackEvidence(data: Record<string, any>) {
  // Real analysed events should always win. Some older worker responses can contain
  // stale fallback wording inside analysis text even though frame analysis succeeded.
  if (hasRealAnalysedEvents(data)) return false

  const analysis = String(data?.analysis ?? '')
  if (isFallbackText(analysis)) return true

  const events = Array.isArray(data?.eventCandidates) ? data.eventCandidates : []
  if (!events.length) return false

  const fallbackCount = events.filter((event: any) => isFallbackText(event?.reason) || isFallbackText(event?.visualAnalysis)).length
  return fallbackCount > 0 && fallbackCount >= Math.max(3, Math.floor(events.length * 0.5))
}

function buildTimelineFromWorker(data: Record<string, any>): TimelineItem[] {
  if (hasFallbackEvidence(data)) return []

  const surfacedClips = data?.matchEvidence?.clipSurface?.priorityClips || data?.debug?.matchEvidence?.clipSurface?.priorityClips || []
  if (Array.isArray(surfacedClips) && surfacedClips.length) {
    return surfacedClips
      .filter((clip: any) => !isFallbackText(clip?.reason) && !isFallbackText(clip?.clipLabel))
      .slice(0, 20)
      .map((clip: any) => ({
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
    .filter((event: any) => !isFallbackText(event.reason) && !isFallbackText(event.visualAnalysis))
    .filter((event: any) => event.classification || event.matchIntelligence || event.scoreOutcome || event.kickoutVisual || ['turnover', 'fast_transition', 'kickout_restart', 'breaking_ball', 'scoring_chance'].includes(String(event.type)))
    .slice(0, 20)
    .map((event: any) => ({
      minute: String(event.time ?? 'N/A'),
      note: String(event.visualAnalysis || event.classification?.coachingReason || event.reason || event.kickoutVisual?.reasoning || 'Review this tactical moment.'),
      category: humanise(event.type),
      confidence: String(event.classification?.confidence || event.matchIntelligence?.confidence || event.confidence || 'estimated'),
      reason: String(event.classification?.coachingReason || event.reason || event.kickoutVisual?.reasoning || ''),
      startSecond: Number.isFinite(Number(event.startSecond)) ? Number(event.startSecond) : undefined,
      endSecond: Number.isFinite(Number(event.endSecond)) ? Number(event.endSecond) : undefined,
    }))
}

function fallbackSafeReport(job: Record<string, any>, result: Record<string, any>) {
  return {
    status: 'complete',
    mode: 'worker',
    jobId: job.jobId,
    reportId: result.reportId || job.jobId,
    summary: 'Video scanning was unavailable for this run, so no reliable tactical timeline or kickout events were generated.',
    scoreline: result.matchFacts?.scoreline || 'Unavailable',
    keyInsights: [
      'The final score and match context were received.',
      'The video scan did not produce reliable frame evidence.',
      'Fallback checkpoints have been hidden to avoid showing fake kickouts or false tactical moments.',
    ],
    trainingFocus: [
      'Rerun the analysis after confirming the worker can download and scan the video.',
      'Do not use this run for kickout accuracy review.',
    ],
    timeline: [],
    nextSteps: ['Check Railway logs for download/ffmpeg scan errors, then rerun the same cloud URL.'],
    rawAnalysis: 'Video scan unavailable — no reliable tactical report was generated for this run. Fallback timeline entries were suppressed.',
    debug: {
      progress: job.progress,
      stage: job.stage,
      detail: job.detail,
      fallbackSuppressed: true,
      realAnalysedEvents: hasRealAnalysedEvents(result),
      matchEvidence: result.matchEvidence,
      timelineCount: 0,
      debugReportUrl: result.debugReportUrl,
      latestDebugReportUrl: result.latestDebugReportUrl,
    }
  }
}

function normaliseCompletedJob(job: Record<string, any>) {
  const result = job.result || {}

  if (hasFallbackEvidence(result)) {
    return fallbackSafeReport(job, result)
  }

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
      realAnalysedEvents: hasRealAnalysedEvents(result),
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
