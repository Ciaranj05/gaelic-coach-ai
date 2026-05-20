import { NextResponse } from 'next/server'

type FeedbackRequest = {
  matchTitle?: string
  sourceUrl?: string
  rating?: 'accurate' | 'too_generic' | 'wrong_team' | 'wrong_score' | 'poor_clips'
  notes?: string
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as FeedbackRequest

    if (!body.rating) {
      return NextResponse.json({ error: 'Feedback rating is required.' }, { status: 400 })
    }

    // Production note: persist this to Supabase/Postgres when the database layer is added.
    console.info('Gaelic Coach AI report feedback', {
      matchTitle: body.matchTitle ?? 'Unknown match',
      sourceUrl: body.sourceUrl ?? '',
      rating: body.rating,
      notes: body.notes ?? '',
      createdAt: new Date().toISOString()
    })

    return NextResponse.json({ status: 'saved' })
  } catch {
    return NextResponse.json({ error: 'Unable to save feedback.' }, { status: 500 })
  }
}
