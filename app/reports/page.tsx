import { insights, trainingPlan } from '@/lib/mock-data'

export default function ReportsPage() {
  return (
    <main className="min-h-screen bg-black p-10 text-white">
      <div className="mx-auto max-w-6xl">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-5xl font-bold">AI Match Report</h1>
            <p className="mt-4 text-zinc-400">
              Tactical insights generated from uploaded footage.
            </p>
          </div>

          <button className="rounded-2xl bg-white px-6 py-3 font-semibold text-black">
            Export PDF
          </button>
        </div>

        <div className="mt-12 grid gap-6 lg:grid-cols-2">
          <div className="rounded-3xl border border-white/10 bg-white/5 p-8">
            <h2 className="text-3xl font-bold">Key Insights</h2>

            <div className="mt-6 space-y-4">
              {insights.map((item) => (
                <div
                  key={item}
                  className="rounded-2xl bg-black/40 p-4 text-zinc-300"
                >
                  {item}
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-white/5 p-8">
            <h2 className="text-3xl font-bold">Training Focus</h2>

            <div className="mt-6 space-y-4">
              {trainingPlan.map((item) => (
                <div
                  key={item}
                  className="rounded-2xl bg-green-500/10 p-4 text-green-300"
                >
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}
