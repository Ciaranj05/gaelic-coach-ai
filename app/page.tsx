import Link from 'next/link'
import YouTubeAnalyser from '@/components/youtube-analyser'

export default function HomePage() {
  return (
    <main className="min-h-screen bg-[#f6f8fb] text-slate-950">
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(16,185,129,0.22),transparent_32%),radial-gradient(circle_at_80%_10%,rgba(59,130,246,0.16),transparent_26%),linear-gradient(180deg,#ffffff,rgba(246,248,251,0.65))]" />

        <div className="relative mx-auto max-w-7xl px-6 py-8 lg:px-8">
          <header className="flex items-center justify-between rounded-full border border-white/70 bg-white/75 px-5 py-3 shadow-sm backdrop-blur-xl">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-950 text-sm font-black text-white">
                GC
              </div>
              <div>
                <p className="text-sm font-bold">Gaelic Coach AI</p>
                <p className="text-xs text-slate-500">Sports intelligence platform</p>
              </div>
            </div>

            <div className="hidden items-center gap-6 text-sm font-medium text-slate-600 md:flex">
              <a href="#how-it-works">How it works</a>
              <a href="#features">Features</a>
              <Link href="/reports">Demo report</Link>
            </div>
          </header>

          <div className="grid gap-16 py-20 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:py-28">
            <div>
              <div className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 shadow-sm">
                Link-based AI analysis for Gaelic football and hurling
              </div>

              <h1 className="mt-8 max-w-4xl text-5xl font-black leading-[0.95] tracking-tight text-slate-950 sm:text-7xl">
                Analyse Gaelic games like an elite coaching team.
              </h1>

              <p className="mt-8 max-w-2xl text-lg leading-8 text-slate-600">
                Paste a YouTube, Veo or Vimeo match link and generate tactical themes, training priorities, coaching actions and downloadable reports.
              </p>

              <div className="mt-10 flex flex-wrap gap-4">
                <a
                  href="#analyse"
                  className="rounded-2xl bg-slate-950 px-6 py-4 font-semibold text-white shadow-xl shadow-slate-900/15 transition hover:-translate-y-0.5 hover:bg-slate-800"
                >
                  Analyse a Match Link
                </a>

                <Link
                  href="/reports"
                  className="rounded-2xl border border-slate-200 bg-white px-6 py-4 font-semibold text-slate-900 shadow-sm transition hover:-translate-y-0.5 hover:bg-slate-50"
                >
                  View Sample Report
                </Link>
              </div>

              <div className="mt-12 grid max-w-2xl grid-cols-3 gap-4">
                <div className="rounded-3xl border border-white bg-white/70 p-4 shadow-sm backdrop-blur">
                  <p className="text-2xl font-black">20–60</p>
                  <p className="mt-1 text-xs font-medium text-slate-500">sampled frames</p>
                </div>
                <div className="rounded-3xl border border-white bg-white/70 p-4 shadow-sm backdrop-blur">
                  <p className="text-2xl font-black">AI</p>
                  <p className="mt-1 text-xs font-medium text-slate-500">vision + context</p>
                </div>
                <div className="rounded-3xl border border-white bg-white/70 p-4 shadow-sm backdrop-blur">
                  <p className="text-2xl font-black">HTML</p>
                  <p className="mt-1 text-xs font-medium text-slate-500">report ready</p>
                </div>
              </div>
            </div>

            <div id="analyse" className="space-y-6">
              <YouTubeAnalyser />
            </div>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="mx-auto max-w-7xl px-6 py-16 lg:px-8">
        <div className="max-w-2xl">
          <p className="text-sm font-bold uppercase tracking-[0.25em] text-emerald-600">Workflow</p>
          <h2 className="mt-3 text-4xl font-black tracking-tight text-slate-950">From match link to coaching plan.</h2>
        </div>

        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {[
            ['1', 'Submit Match Link', 'Paste a YouTube, Veo or Vimeo link and add match context.'],
            ['2', 'AI Reviews Context', 'The worker samples frames, extracts metadata and reviews tactical evidence.'],
            ['3', 'Download Report', 'Receive tactical themes, training priorities and a premium downloadable report.']
          ].map(([step, title, body]) => (
            <div key={title} className="rounded-[2rem] border border-white bg-white/80 p-7 shadow-sm shadow-slate-200/70 backdrop-blur-xl">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-950 text-sm font-black text-white">
                {step}
              </div>
              <h3 className="mt-6 text-2xl font-bold text-slate-950">{title}</h3>
              <p className="mt-3 text-sm leading-7 text-slate-600">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="features" className="mx-auto max-w-7xl px-6 pb-24 lg:px-8">
        <div className="rounded-[2.5rem] bg-slate-950 p-8 text-white shadow-2xl shadow-slate-300/40 lg:p-12">
          <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:items-center">
            <div>
              <p className="text-sm font-bold uppercase tracking-[0.25em] text-emerald-300">Platform Preview</p>
              <h2 className="mt-4 text-4xl font-black tracking-tight">Built for modern Gaelic coaches.</h2>
              <p className="mt-5 text-sm leading-7 text-slate-300">
                Move beyond raw AI text. Turn footage links into executive summaries, tactical cards, training plans, timelines and team learning moments.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              {[
                ['Tactical Themes', 'Attack, defence, transitions and restarts.'],
                ['Training Priorities', 'Session-ready actions for the next week.'],
                ['Timeline Moments', 'Key moments converted into coach review points.'],
                ['Download Reports', 'Shareable outputs for coaches and players.']
              ].map(([title, body]) => (
                <div key={title} className="rounded-3xl border border-white/10 bg-white/10 p-5 backdrop-blur">
                  <h3 className="font-bold">{title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-300">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  )
}
