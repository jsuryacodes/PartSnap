import { useEffect, useRef, useState } from 'react'
import { generate, reviewOverride, type GenEvent, type Stl, type Usage, type VerifyResult } from './api'
import type { Params } from './Measure'
import { ModelTag } from './ui'

type Design = GenEvent & { type: 'design' }
type Attempt = { n: number; by: string; design?: Design; verifies: VerifyResult[] }
type Review = GenEvent & { type: 'review' }
export type Done = { review?: Review; overridden?: boolean; stls: Stl[]; mate_url?: string; verify: VerifyResult; attempts: number; by: string; rationale?: string; trimmed_mm?: number }

const pad = (n: number) => String(n).padStart(2, '0')
const tokens = (u: Usage) => [u.prompt_tokens && `${u.prompt_tokens} in`, u.completion_tokens && `${u.completion_tokens} out`,
  u.reasoning_tokens && `${u.reasoning_tokens} reasoning`].filter(Boolean).join(' · ')

export default function Generate({ fix, params, shape, onDone }: { fix: string; params: Params; shape: unknown; onDone: (d: Done) => void }) {
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [done, setDone] = useState<(GenEvent & { type: 'done' }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [review, setReview] = useState<Review | null>(null)
  const [overriding, setOverriding] = useState(false)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return // StrictMode runs effects twice in dev; generate once
    started.current = true
    generate(fix, params, shape, (e) => {
      if (e.type === 'done') return setDone(e)
      if (e.type === 'error') return setError(e.message)
      if (e.type === 'review') return setReview(e)
      setAttempts((a) => {
        if (e.type === 'attempt') return [...a, { n: e.n, by: e.by, verifies: [] }]
        return a.map((x) => x.n !== e.n ? x : e.type === 'design' ? { ...x, design: e } : { ...x, verifies: [...x.verifies, e] })
      })
    }).catch((e) => setError(e.message))
  }, [])

  const last = attempts.at(-1)
  const passed = last?.verifies.find((v) => v.ok && v.clearance === params.clearance)
  const heading = done ? (done.ok ? 'Part verified' : 'Could not generate a fix') : error ? 'Something went wrong' : 'Designing your part…'
  return (
    <div className="screen">
      <p className="eyebrow">CAD agent · <span className="accent">{fix.replace('_', ' ')}</span></p>
      <h2 className="title">{heading}</h2>
      <p className="lede">The agent writes CadQuery from your outlines and measurements; every attempt is built and inspected, at {params.clearance} mm clearance and then the other setting. Failures go back to the agent with the inspector's notes.</p>
      <div className="byline">CAD by <ModelTag>Muse Wonder</ModelTag> inspected by <span className="mono">CadQuery</span> reviewed by <ModelTag>Muse Spark Open</ModelTag></div>

      {attempts.map((a, i) => (
        <div key={a.n}>
          {i > 0 && <div className="handoff">↳ inspection notes sent back to {attempts[i - 1].design?.by ?? 'Muse Wonder'}</div>}
          <AttemptCard a={a} />
        </div>
      ))}
      {error && <p className="notice">{error}</p>}
      {done && !done.ok && <p className="notice">Failed inspection after {done.attempts} attempts, so no STL was released. Check the measurements and try again.</p>}
      {passed && last!.verifies.filter((v) => v.ok).length === 2 && <ReviewCard r={review} />}
      {done?.ok && done.stls && passed && (() => {
        const finish = (overridden: boolean) => onDone({ stls: done.stls!, mate_url: done.mate_url, verify: passed, review: review ?? undefined,
          overridden, attempts: done.attempts, by: last?.design?.by ?? 'Muse Wonder', rationale: done.rationale, trimmed_mm: done.trimmed_mm })
        if (done.review !== 'reject') return (
          <div className="cta-bar">
            <button className="btn btn-primary btn-block" onClick={() => finish(false)}>View part &amp; download <span className="arrow">→</span></button>
          </div>
        )
        return (
          <div className="cta-bar">
            <p className="notice" style={{ marginTop: 0, marginBottom: 10 }}>The reviewer has concerns, so the downloads are held. Read them above; if you still want the part, downloading is put on the record in the agent log.</p>
            <button className="btn btn-ghost btn-block" disabled={overriding} onClick={async () => {
              setOverriding(true)
              try { await reviewOverride(done.run!); finish(true) } catch (e) { setError((e as Error).message); setOverriding(false) }
            }}>{overriding ? 'Recording…' : 'Download anyway'} <span className="arrow">→</span></button>
          </div>
        )
      })()}
    </div>
  )
}

const STAMP = { approve: ['pass', 'APPROVED'], reject: ['fail', 'CONCERNS'], unavailable: ['', 'UNAVAILABLE'] } as const

function ReviewCard({ r }: { r: Review | null }) {
  return (
    <>
      <div className="handoff">↳ verified part sent to an independent reviewer</div>
      <article className="attempt">
        <header className="attempt-head">
          <span className="eyebrow">Review <ModelTag>Muse Spark Open</ModelTag></span>
          {r ? <span className={`stamp ${STAMP[r.verdict][0]}`}>{STAMP[r.verdict][1]}</span> : <span className="status">Muse Spark Open is reviewing</span>}
        </header>
        <div className="attempt-body">
          {!r && <><div className="skeleton" /><div className="skeleton short" /></>}
          {r && <ul className="review-notes">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          {r?.verdict === 'unavailable' && <p className="reasoning">Released without a review: it is advisory, and the part passed every geometric check.</p>}
          {r?.reasoning && (
            <details className="panel">
              <summary>Reviewer's reasoning {r.usage && <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{tokens(r.usage)}</span>}</summary>
              <p className="reasoning" style={{ whiteSpace: 'pre-wrap' }}>{r.reasoning}</p>
            </details>
          )}
        </div>
      </article>
    </>
  )
}

function AttemptCard({ a }: { a: Attempt }) {
  const d = a.design
  const status = a.verifies.length ? (a.verifies.every((v) => v.ok) && a.verifies.length === 2 ? 'pass' : a.verifies.some((v) => !v.ok) ? 'fail' : null) : null
  return (
    <article className="attempt">
      <header className="attempt-head">
        <span className="eyebrow">Attempt {pad(a.n)}{a.n > 1 && <span className="chip">Repair</span>}</span>
        {status ? <span className={`stamp ${status}`}>{status.toUpperCase()}</span>
          : <span className="status">{!d ? `${a.by} is designing` : 'Inspecting geometry'}</span>}
      </header>
      <div className="attempt-body">
        {!d && <><div className="skeleton" /><div className="skeleton short" /></>}
        {d && (
          <details className="panel" open>
            <summary>Agent's rationale <ModelTag>{d.by}</ModelTag>
              {d.usage && <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{tokens(d.usage)}</span>}</summary>
            <p className="reasoning">{d.rationale ?? d.error}</p>
            {d.trimmed_mm !== undefined && <p className="reasoning mono" style={{ fontSize: 12 }}>declares {d.trimmed_mm} mm trimmed off the thin ends</p>}
          </details>
        )}
        {d?.code && (
          <details className="panel">
            <summary>CadQuery source <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{d.code.trim().split('\n').length} lines · {d.code_hash}</span></summary>
            <pre>{d.code}</pre>
          </details>
        )}
        {d && !a.verifies.length && <><div className="skeleton" /><div className="skeleton" /><div className="skeleton short" /></>}
        {a.verifies.map((v, i) => (
          <div key={v.clearance + '-' + i}>
            {(a.verifies.length > 1 || v.checks.length > 0) && <p className="eyebrow" style={{ margin: '10px 0 4px' }}>Inspection · {v.clearance} mm clearance</p>}
            <Checks v={v} />
          </div>
        ))}
      </div>
    </article>
  )
}

/** The inspector's rows, exactly as backend/verify.py judged them. */
export function Checks({ v }: { v: VerifyResult }) {
  if (!v.checks.length) return <p className="err">{v.error}</p> // crashed or unparseable before any geometry
  const notes = v.error?.split('; ') ?? []
  return (
    <>
      <ul className="checklist">
        {v.checks.map((c, i) => (
          <li key={c.name} className={c.ok ? 'ok' : 'bad'} style={{ animationDelay: `${i * 45}ms` }}>
            <span className="box">{c.ok ? '✓' : '✗'}</span>
            <span className="label">{c.name}</span>
            <span className="val">{c.value}{c.expected && <small>expected {c.expected}</small>}</span>
          </li>
        ))}
      </ul>
      {notes.length > 0 && (
        <details className="panel notes" open={notes.length < 3}>
          <summary>Inspector’s notes <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{notes.length}</span></summary>
          <ul>{notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </details>
      )}
    </>
  )
}
