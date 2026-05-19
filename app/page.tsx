import Link from 'next/link'
import UploadCard from '@/components/upload-card'
import YouTubeAnalyser from '@/components/youtube-analyser'

export default function HomePage() {
  return (
    <main className="min-h-screen bg-black text-white">
      <section className="relative overflow-hidden border-b border-white/10">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(34,197,94,0.22),transparent_35%),radial-gradient(circle_at_bottom_right,rgba(59,130,246,0.2),transparent_35%)]" />

        <div className="relative mx-auto max-w-7xl px-6 py-24 lg:px-8">
          <div className="grid gap-16 lg:grid-cols-2 lg:items-center">
            <div>
              <div className="inline-flex rounded-full border border-green-400/20 bg-green-400/10 px-4 py-2 text-sm text-green-300">
                AI-powered analysis for Gaelic coaches
              </div>

              <h1 className="mt-8 text-6xl font-black leading-tight tracking-tight lg:text-7xl">
                Turn match footage into coaching insights.
              </h1>

              <p className="mt-8 max-w-2xl text-lg leading-8 text-zinc-400">
                Analyse Gaelic football and hurling matches using uploads or YouTube/Veo links.
              </p>

              <div className="mt-10 flex flex-wrap gap-4">
                <Link
                  href="/reports"
                  className="rounded-2xl bg-green-400 px-6 py-4 font-semibold text-black transition hover:bg-green-300"
                >
                  View Demo Report
                </Link>

                <Link
                  href="/upload"
                  className="rounded-2xl border border-white/10 bg-white/5 px-6 py-4 font-semibold backdrop-blur transition hover:bg-white/10"
                >
                  Upload Match
                </Link>
              </div>
            </div>

            <div className="space-y-6">
              <UploadCard />
              <YouTubeAnalyser />
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-20 lg:px-8">
        <div className="grid gap-6 md:grid-cols-3">
          <div className="rounded-[2rem] border border-white/10 bg-white/[0.05] p-8">
            <h2 className="text-3xl font-bold">Upload Matches</h2>
            <p className="mt-4 text-zinc-400">
              Upload full games from Veo, phones, drones, or sideline cameras.
            </p>
          </div>

          <div className="rounded-[2rem] border border-white/10 bg-white/[0.05] p-8">
            <h2 className="text-3xl font-bold">Analyse Links</h2>
            <p className="mt-4 text-zinc-400">
              Paste YouTube, Vimeo, or Veo links to create AI-powered coaching reports.
            </p>
          </div>

          <div className="rounded-[2rem] border border-white/10 bg-white/[0.05] p-8">
            <h2 className="text-3xl font-bold">Create Clips</h2>
            <p className="mt-4 text-zinc-400">
              Automatically create clips for scores, turnovers, and kickout sequences.
            </p>
          </div>
        </div>
      </section>
    </main>
  )
}
