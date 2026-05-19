export default function Sidebar() {
  const items = ['Dashboard', 'Matches', 'Reports', 'Players', 'Settings']

  return (
    <aside className="w-64 border-r border-white/10 bg-zinc-950 p-6">
      <h1 className="text-2xl font-bold text-green-400">Gaelic Coach AI</h1>

      <nav className="mt-10 space-y-3">
        {items.map((item) => (
          <div
            key={item}
            className="rounded-2xl px-4 py-3 text-zinc-300 transition hover:bg-white/5 hover:text-white"
          >
            {item}
          </div>
        ))}
      </nav>
    </aside>
  )
}
