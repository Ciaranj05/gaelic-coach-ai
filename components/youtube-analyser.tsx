'use client'

import { useState } from 'react'

type Status = 'idle' | 'ready' | 'processing' | 'complete' | 'error'

function isVideoUrl(value: string) {
  return value.includes('youtube.com') || value.includes('youtu.be') || value.includes('vimeo.com') || value.includes('veo.co')
}

export default function YouTubeAnalyser() {
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [step, setStep] = useState(0)

  const steps = [
    'Fetching match link',
    'Preparing video timeline',
    'Extracting key moments',
    'Generating coaching report'
  ]

  function analyse() {
    if (!isVideoUrl(url)) {
      setStatus('error')
      return
    }

    setStatus('processing')
    setStep(0)

    const timer = window.setInterval(() => {
      setStep((current) => {
        if (current >= steps.length - 1) {
          window.clearInterval(timer)
          setStatus('complete')
          return current
        }

        return current + 1
      })
    }, 900)
  }

  return (
    <div className="rounded-[2rem] border border-white/10 bg-white/[0.06] p-6 shadow-2xl shadow-green-950/20 backdrop-blur">
      <p className="text-xl font-semibold">Analyse a match link</p>
      <p className="mt-2 text-sm text-zinc-400">
        Paste a YouTube, Vimeo or Veo link to generate a demo coaching report.
      </p>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <input
          value={url}
          onChange={(event) => {
            setUrl(event.target.value)
            setStatus(event.target.value ? 'ready' : 'idle')
          }}
          placeholder="https://youtube.com/watch?v=..."
          className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-black/50 px-4 py-4 text-white outline-none placeholder:text-zinc-600 focus:border-green-400/60"
        />

        <button
          onClick={analyse}
          disabled={!url || status === 'processing'}
          className="rounded-2xl bg-green-400 px-6 py-4 font-semibold text-black transition hover:bg-green-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Analyse Link
        </button>
      </div>

      {status === 'error' ? (
        <div className="mt-5 rounded-2xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-300">
          Please enter a valid YouTube, Vimeo, or Veo link.
        </div>
      ) : null}

      {status === 'processing' ? (
        <div className="mt-6 space-y-3">
          {steps.map((item, index) => (
            <div
              key={item}
              className={`rounded-2xl p-4 text-sm ${index <= step ? 'bg-green-400/10 text-green-300' : 'bg-black/40 text-zinc-500'}`}
            >
              {item}
            </div>
          ))}
        </div>
      ) : null}

      {status === 'complete' ? (
        <div className="mt-6 rounded-2xl bg-green-400/10 p-5 text-sm text-green-300">
          Demo report generated. Next step is connecting this to a backend video processor and AI analysis service.
        </div>
      ) : null}
    </div>
  )
}
