import './globals.css'
import { ReactNode } from 'react'

export const metadata = {
  title: 'Gaelic Coach AI',
  description: 'AI-powered match analysis for Gaelic coaches'
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
