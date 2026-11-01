import { useEffect, useRef, useState } from 'react'
import { generate, type GenEvent, type VerifyResult } from './api'
import type { Params } from './Measure'

type Attempt = { n: number; by: string; reasoning?: string | null; code?: string; verify?: VerifyResult }
export type Done = { stl_url: string; verify: VerifyResult; attempts: number }

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
  return (
    <div className="screen">
      <h2>{done ? (done.ok ? 'Fix verified ✓' : 'Could not generate a fix') : error ? 'Something went wrong' : 'Designing your fix…'}</h2>
      <p className="by">CAD by Muse Spark Open · verified by CadQuery geometry checks</p>
      {attempts.map((a) => <AttemptCard key={a.n} a={a} clearance={params.clearance} />)}
      {error && <p className="warn">{error}</p>}
      {done?.ok && done.stl_url && last && (
        <button className="wide" onClick={() => onDone({ stl_url: done.stl_url!, verify: last, attempts: done.attempts })}>See your part</button>
      )}
      {done && !done.ok && <p className="warn">Failed verification after {done.attempts} attempts. Check the measurements and try again.</p>}
    </div>
  )
}

function AttemptCard({ a, clearance }: { a: Attempt; clearance: number }) {
  const v = a.verify
  const status = !a.code ? 'Writing CadQuery…' : !v ? 'Verifying geometry…' : v.ok ? 'Passed' : 'Failed, sending error back to the model'
  return (
    <div className={`card ${v ? (v.ok ? 'pass' : 'fail') : ''}`}>
      <div className="card-head">
        <b>Attempt {a.n}{a.n > 1 ? ' (repair)' : ''}</b>
        <span>{status}</span>
      </div>
      {a.reasoning && <details open><summary>{a.by} reasoning</summary><p className="reasoning">{a.reasoning}</p></details>}
      {a.code && <details><summary>CadQuery code</summary><pre>{a.code}</pre></details>}
      {v && <Checks v={v} clearance={clearance} />}
    </div>
  )
}

export function Checks({ v, clearance }: { v: VerifyResult; clearance: number }) {
  if (v.watertight === undefined) return <p className="warn">{v.error}</p> // code crashed before any geometry
  const bboxOk = v.bbox!.every((x, i) => Math.abs(x - v.expected_bbox![i]) <= 0.2)
  const rows: [boolean, string, string][] = [
    [v.watertight! && v.bodies === 1, 'Watertight, single body', v.watertight ? `${v.bodies} body` : 'not watertight'],
    [bboxOk, 'Size', `${v.bbox!.join(' × ')} mm (want ${v.expected_bbox!.join(' × ')})`],
    [v.interference_volume! <= 1e-6, 'Overlap with table', `${v.interference_volume} mm³`],
    ...Object.entries(v.gaps ?? {}).map(([face, g]): [boolean, string, string] => [Math.abs(g - clearance) <= 0.1, `Gap ${face}`, `${g} mm (want ${clearance})`]),
  ]
  return (
    <>
      <ul className="checks">
        {rows.map(([ok, label, val]) => <li key={label} className={ok ? 'ok' : 'bad'}><span>{ok ? '✓' : '✗'} {label}</span><span>{val}</span></li>)}
      </ul>
      {v.error && <p className="warn small">{v.error}</p>}
    </>
  )
}
