type StatCardProps = {
  label: string
  value: string
  helper?: string
}

export default function StatCard({ label, value, helper }: StatCardProps) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
      <p className="text-sm text-zinc-400">{label}</p>
      <h2 className="mt-4 text-5xl font-bold">{value}</h2>
      {helper ? <p className="mt-3 text-sm text-zinc-500">{helper}</p> : null}
    </div>
  )
}
