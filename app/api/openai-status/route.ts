import { NextResponse } from 'next/server'

export async function GET() {
  const apiKey = process.env.OPENAI_API_KEY

  if (!apiKey) {
    return NextResponse.json({
      connected: false,
      status: 'missing_key',
      message: 'OPENAI_API_KEY is not available to this deployment.'
    })
  }

  try {
    const response = await fetch('https://api.openai.com/v1/models', {
      headers: {
        Authorization: `Bearer ${apiKey}`
      },
      cache: 'no-store'
    })

    if (!response.ok) {
      return NextResponse.json({
        connected: false,
        status: 'openai_rejected_key',
        message: 'OpenAI rejected the configured API key.'
      })
    }

    return NextResponse.json({
      connected: true,
      status: 'connected',
      message: 'OpenAI API key is configured and reachable.'
    })
  } catch {
    return NextResponse.json({
      connected: false,
      status: 'connection_failed',
      message: 'Unable to reach OpenAI from this deployment.'
    })
  }
}
