import { useEffect, useRef, useState } from 'react'
import { generate, type GenEvent, type VerifyResult } from './api'
import type { Params } from './Measure'
import { ModelTag } from './ui'

type Attempt = { n: number; by: string; reasoning?: string | null; code?: string; verify?: VerifyResult }
export type Done = { stl_url: string; verify: VerifyResult; attempts: number }

const pad = (n: number) => String(n).padStart(2, '0')

export default function Generate({ fix, params, onDone }: { fix: string; params: Params; onDone: (d: Done) => void }) {
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [done, setDone] = useState<(GenEvent & { type: 'done' }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return // StrictMode runs effects twice in dev; generate once
    started.current = true
    generate(fix, params, (e) => {
      if (e.type === 'done') return setDone(e)
      if (e.type === 'error') return setError(e.message)
      setAttempts((a) => {
        if (e.type === 'attempt') return [...a, { n: e.n, by: e.by }]
        return a.map((x) => x.n !== e.n ? x : e.type === 'code' ? { ...x, reasoning: e.reasoning, code: e.code } : { ...x, verify: e })
      })
    }).catch((e) => setError(e.message))
  }, [])

  const last = attempts.at(-1)?.verify
  const heading = done ? (done.ok ? 'Part verified' : 'Could not generate a fix') : error ? 'Something went wrong' : 'Designing your part…'
  return (
    <div className="screen">
      <p className="eyebrow">CAD generation · <span className="accent">{fix.replace('_', ' ')}</span></p>
      <h2 className="title">{heading}</h2>
      <p className="lede">The model writes CadQuery code; every attempt is built and inspected against your measurements. Failures go back to the model with the inspector's notes.</p>
      <div className="byline">CAD by <ModelTag>Muse Spark Open</ModelTag> inspected by <span className="mono">CadQuery</span></div>

      {attempts.map((a, i) => (
        <div key={a.n}>
          {i > 0 && <div className="handoff">↳ inspection notes sent back to Muse Spark Open</div>}
          <AttemptCard a={a} clearance={params.clearance} />
        </div>
      ))}
      {error && <p className="notice">{error}</p>}
      {done && !done.ok && <p className="notice">Failed inspection after {done.attempts} attempts. Check the measurements and try again.</p>}
      {done?.ok && done.stl_url && last && (
        <div className="cta-bar">
          <button className="btn btn-primary btn-block" onClick={() => onDone({ stl_url: done.stl_url!, verify: last, attempts: done.attempts })}>
            View part &amp; download <span className="arrow">→</span>
          </button>
        </div>
      )}
    </div>
  )
}

function AttemptCard({ a, clearance }: { a: Attempt; clearance: number }) {
  const v = a.verify
  return (
    <article className="attempt">
      <header className="attempt-head">
        <span className="eyebrow">Attempt {pad(a.n)}{a.n > 1 && <span className="chip">Repair</span>}</span>
        {v ? <span className={`stamp ${v.ok ? 'pass' : 'fail'}`}>{v.ok ? 'PASS' : 'FAIL'}</span>
          : <span className="status">{!a.code ? 'Writing CadQuery' : 'Inspecting geometry'}</span>}
      </header>
      <div className="attempt-body">
        {!a.code && <><div className="skeleton" /><div className="skeleton short" /></>}
        {a.reasoning && (
          <details className="panel" open>
            <summary>Model reasoning <ModelTag>{a.by}</ModelTag></summary>
            <p className="reasoning">{a.reasoning}</p>
          </details>
        )}
        {a.code && (
          <details className="panel">
            <summary>CadQuery source <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{a.code.trim().split('\n').length} lines</span></summary>
            <pre>{a.code}</pre>
          </details>
        )}
        {a.code && !v && <><div className="skeleton" /><div className="skeleton" /><div className="skeleton short" /></>}
        {v && <Checks v={v} clearance={clearance} />}
      </div>
    </article>
  )
}

export function Checks({ v, clearance }: { v: VerifyResult; clearance: number }) {
  if (v.watertight === undefined) return <p className="err">{v.error}</p> // code crashed before any geometry
  const bboxOk = v.bbox!.every((x, i) => Math.abs(x - v.expected_bbox![i]) <= 0.2)
  const fmt = (xs: number[]) => xs.map((x) => x.toFixed(1)).join(' × ')
  const rows: [boolean, string, string, string?][] = [
    [v.watertight! && v.bodies === 1, 'Watertight, single body', v.watertight ? `${v.bodies} body` : 'open mesh'],
    [bboxOk, 'Overall size', `${fmt(v.bbox!)}`, `nominal ${fmt(v.expected_bbox!)}`],
    [v.interference_volume! <= 1e-6, 'Overlap with table', `${v.interference_volume!.toFixed(3)} mm³`],
    ...Object.entries(v.gaps ?? {}).map(([face, g]): [boolean, string, string, string] =>
      [Math.abs(g - clearance) <= 0.1, `Clearance, face ${face}`, `${g.toFixed(2)} mm`, `nominal ${clearance.toFixed(2)} ±0.10`]),
  ]
  return (
    <>
      <ul className="checklist">
        {rows.map(([ok, label, val, sub], i) => (
          <li key={label} className={ok ? 'ok' : 'bad'} style={{ animationDelay: `${i * 45}ms` }}>
            <span className="box">{ok ? '✓' : '✗'}</span>
            <span className="label">{label}</span>
            <span className="val">{val}{sub && <small>{sub}</small>}</span>
          </li>
        ))}
      </ul>
      {v.error && <p className="err">{v.error}</p>}
    </>
  )
}
