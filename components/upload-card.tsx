'use client'

import { useState } from 'react'

type UploadState = 'idle' | 'selected' | 'processing' | 'complete'

export default function UploadCard() {
  const [fileName, setFileName] = useState('')
  const [state, setState] = useState<UploadState>('idle')

  function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return

    setFileName(file.name)
    setState('selected')
  }

  function startAnalysis() {
    setState('processing')

    window.setTimeout(() => {
      setState('complete')
    }, 1600)
  }

  return (
    <div className="rounded-[2rem] border border-white/10 bg-white/[0.06] p-6 shadow-2xl shadow-green-950/20 backdrop-blur">
      <div className="rounded-[1.5rem] border-2 border-dashed border-white/15 bg-black/40 p-8 text-center">
        <p className="text-xl font-semibold">Upload match footage</p>
        <p className="mt-2 text-sm text-zinc-400">Veo, phone, drone or camera footage</p>

        <label className="mt-6 inline-flex cursor-pointer rounded-2xl bg-green-400 px-5 py-3 font-semibold text-black transition hover:bg-green-300">
          Choose video
          <input type="file" accept="video/*" onChange={onFileChange} className="hidden" />
        </label>
      </div>

      {fileName ? (
        <div className="mt-5 rounded-2xl border border-white/10 bg-black/40 p-4">
          <p className="text-sm text-zinc-400">Selected file</p>
          <p className="mt-1 font-medium">{fileName}</p>
        </div>
      ) : null}

      <button
        onClick={startAnalysis}
        disabled={!fileName || state === 'processing'}
        className="mt-5 w-full rounded-2xl bg-white px-5 py-4 font-semibold text-black transition disabled:cursor-not-allowed disabled:opacity-40"
      >
        {state === 'processing' ? 'Processing footage...' : 'Generate AI match report'}
      </button>

      {state === 'complete' ? (
        <div className="mt-5 rounded-2xl bg-green-400/10 p-4 text-sm text-green-300">
          Demo analysis complete. Real video storage and AI processing will be connected next.
        </div>
      ) : null}
    </div>
  )
}
