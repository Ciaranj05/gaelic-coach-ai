export default function UploadPage() {
  return (
    <main className="min-h-screen bg-black p-10 text-white">
      <div className="mx-auto max-w-4xl">
        <h1 className="text-5xl font-bold">Upload Match</h1>

        <p className="mt-4 text-zinc-400">
          Upload full match footage for AI-powered analysis.
        </p>

        <div className="mt-12 rounded-3xl border-2 border-dashed border-white/10 bg-white/5 p-20 text-center">
          <p className="text-2xl font-semibold">
            Drag and drop match footage
          </p>

          <p className="mt-4 text-zinc-500">
            Supports Veo, phone, and camera footage.
          </p>

          <button className="mt-8 rounded-2xl bg-green-500 px-6 py-4 font-semibold text-black">
            Select Video
          </button>
        </div>

        <div className="mt-12 rounded-3xl border border-white/10 bg-white/5 p-8">
          <h2 className="text-2xl font-bold">Processing Pipeline</h2>

          <div className="mt-6 space-y-4">
            <div className="rounded-2xl bg-black/40 p-4">
              1. Upload and compression
            </div>

            <div className="rounded-2xl bg-black/40 p-4">
              2. Timeline generation
            </div>

            <div className="rounded-2xl bg-black/40 p-4">
              3. AI analysis and insights
            </div>

            <div className="rounded-2xl bg-black/40 p-4">
              4. Report and clip generation
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}
