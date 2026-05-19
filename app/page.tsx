export default function HomePage() {
  return (
    <main className="min-h-screen bg-black text-white p-10">
      <h1 className="text-6xl font-bold">Gaelic Coach AI</h1>
      <p className="mt-6 text-zinc-400 text-xl max-w-2xl">
        AI-powered match analysis for Gaelic football and hurling coaches.
      </p>

      <div className="mt-12 grid gap-6 md:grid-cols-3">
        <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="text-2xl font-semibold">Upload Matches</h2>
          <p className="mt-3 text-zinc-400">
            Upload full match footage from any device.
          </p>
        </div>

        <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="text-2xl font-semibold">Generate Reports</h2>
          <p className="mt-3 text-zinc-400">
            AI tactical summaries and coaching insights.
          </p>
        </div>

        <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="text-2xl font-semibold">Create Clips</h2>
          <p className="mt-3 text-zinc-400">
            Automatically build highlight and analysis clips.
          </p>
        </div>
      </div>
    </main>
  )
}
