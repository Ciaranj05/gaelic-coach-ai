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
}

type AnalyseRequest = {
  url?: string
  notes?: string
  matchContext?: MatchContext
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
  timeline: { minute: string; note: string }[]
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
    url.includes('drive.google.com')
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

function buildDemoReport(url: string, matchContext?: MatchContext, reportId = randomUUID()): CoachingReport {
  return {
    reportId,
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
    ],
    debug: {
      reportId,
      mode: 'demo',
      sourceUrl: url,
      supportedProviders: ['YouTube', 'Vimeo', 'Veo', 'Google Drive']
    }
  }
}
