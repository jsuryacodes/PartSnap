import type { ReactNode } from 'react'

export function ModelTag({ children }: { children: ReactNode }) {
  return <span className="mtag">{children}</span>
}

export function Footer() {
  return (
    <footer className="footer">
      <span>Built for the Meta AI Developer Hackathon</span>
      <span className="tags"><ModelTag>Muse Spark</ModelTag><ModelTag>SAM 3.1</ModelTag><ModelTag>Muse Wonder</ModelTag><ModelTag>Muse Spark Open</ModelTag></span>
      <a href="https://github.com/jsuryacodes/PartSnap" target="_blank" rel="noreferrer">GitHub ↗</a>
    </footer>
  )
}

export function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="4" fill="var(--ink)" />
      <path d="M9 23V9h14" fill="none" stroke="var(--accent)" strokeWidth="4" />
    </svg>
  )
}

/** Shared arrowhead marker for dimension lines; `color` sets the fill. */
export function ArrowDefs({ id, color }: { id: string; color: string }) {
  return (
    <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
      <path d="M0,1.5 L10,5 L0,8.5 z" fill={color} />
    </marker>
  )
}
