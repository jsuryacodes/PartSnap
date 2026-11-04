import { useEffect, useRef, useState } from 'react'
import { diagnose, type Diagnosis, type Measurement, type Photos, type View } from './api'
import { ArrowDefs, ModelTag } from './ui'

export type Params = Record<string, number>
type Pt = [number, number]

const VIEW_NAME: Record<View, string> = { top: 'Top view', side: 'Front view', closeup: 'Close-up' }
const VIEWS = Object.keys(VIEW_NAME) as View[]

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const el = ref.current!
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, size] as const
}

/** A drawing-style dimension: extension lines, arrowed dimension line offset outward, mono label. */
function Dim({ a, b, n, value, w, h }: { a: Pt; b: Pt; n: string; value: string; w: number; h: number }) {
  const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1
  let nx = dy / len, ny = -dx / len
  const mid: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
  if ((mid[0] - w / 2) * nx + (mid[1] - h / 2) * ny < 0) { nx = -nx; ny = -ny } // offset away from the photo centre
  const off = 16
  const A: Pt = [a[0] + nx * off, a[1] + ny * off], B: Pt = [b[0] + nx * off, b[1] + ny * off]
  const text = `${value ? Number(value).toFixed(1) : '—'} mm`
  const lw = 26 + text.length * 7
  // Label sits on the line; if the line is too short to carry it, move it outside, beside the line.
  const push = len < lw + 12 ? Math.abs(nx) * (lw / 2 + 8) + Math.abs(ny) * 16 : 2
  const M: Pt = [(A[0] + B[0]) / 2 + nx * push, (A[1] + B[1]) / 2 + ny * push]
  return (
    <g className={`dim ${value ? 'filled' : ''}`}>
      <line className="dim-ext" x1={a[0] + nx * 3} y1={a[1] + ny * 3} x2={A[0] + nx * 5} y2={A[1] + ny * 5} />
      <line className="dim-ext" x1={b[0] + nx * 3} y1={b[1] + ny * 3} x2={B[0] + nx * 5} y2={B[1] + ny * 5} />
      <line className="dim-halo" x1={A[0]} y1={A[1]} x2={B[0]} y2={B[1]} />
      <line className="dim-line" x1={A[0]} y1={A[1]} x2={B[0]} y2={B[1]} markerStart="url(#m-arrow)" markerEnd="url(#m-arrow)" />
      <g className="dim-label" transform={`translate(${M[0]},${M[1]})`}>
        <rect x={-lw / 2} y={-10} width={lw} height={20} rx={2} />
        <text x={-lw / 2 + 7} y={4}><tspan className="n">{n}</tspan><tspan dx="6">{text}</tspan></text>
      </g>
    </g>
  )
}

function DimPhoto({ view, src, d, values }: { view: View; src?: string; d: Diagnosis; values: Record<string, string> }) {
  const [ref, { w, h }] = useSize<HTMLDivElement>()
  const px = (p: Pt): Pt => [p[0] * w, p[1] * h]
  const dims = d.measurements.map((m, i) => [m, tag(m, i)] as [Measurement, string]).filter(([m]) => m.photo === view)
  return (
    <div className="photo" ref={ref}>
      {src && <img src={src} alt={VIEW_NAME[view]} />}
      {w > 0 && (
        <svg className="overlay" viewBox={`0 0 ${w} ${h}`}>
          <defs>
            <ArrowDefs id="m-arrow" color="var(--accent)" />
            <pattern id={`hatch-${view}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="rgba(255,91,20,0.15)" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--accent)" strokeWidth="2" />
            </pattern>
          </defs>
          {d.outlines[view] && (
            <polygon className="damage" fill={`url(#hatch-${view})`} points={d.outlines[view].map((p) => px(p).join(',')).join(' ')} />
          )}
          {dims.map(([m, n]) => <Dim key={m.key} a={px(m.line[0])} b={px(m.line[1])} n={n} value={values[m.key] ?? ''} w={w} h={h} />)}
        </svg>
      )}
      <span className="caption">{VIEW_NAME[view]}</span>
    </div>
  )
}

const tag = (m: Measurement, i: number) => m.letter ?? String(i + 1)
const MISMATCH = 1.4 // hero photos: 0.97 (top), 1.16 (front)

/** Straight-on photos have the same mm per px along and across the edge; a big mismatch means a typo or an angled
 * photo. A sets "along" in both photos; B sets "across" in the top photo, C in the front photo. */
function scaleWarning(d: Diagnosis, values: Record<string, string>) {
  const [a, b, c] = ['edge_length_mm', 'top_depth_mm', 'front_depth_mm'].map((k) => Number(values[k]))
  if (!d.extent_px || !(a > 0)) return null
  const off = ([along, across]: [number, number], depth: number) => {
    if (!(depth > 0) || !(along > 0) || !(across > 0)) return false
    const r = (a / along) / (depth / across)
    return r > MISMATCH || r < 1 / MISMATCH
  }
  const bad = [off(d.extent_px.top, b) && 'A and B', off(d.extent_px.front, c) && 'A and C'].filter(Boolean)
  return bad.length ? `${bad.join(', and ')} don't match the photos' proportions. Check for a typo, or that the photo was taken straight on.` : null
}

export default function Measure({ photos, onDone }: { photos: Photos; onDone: (d: Diagnosis, p: Params) => void }) {
  const [d, setD] = useState<Diagnosis | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [urls, setUrls] = useState<Partial<Record<View, string>>>({})
  useEffect(() => {
    const u = Object.fromEntries(Object.entries(photos).map(([k, b]) => [k, URL.createObjectURL(b)]))
    setUrls(u)
    return () => Object.values(u).forEach(URL.revokeObjectURL)
  }, [photos])

  const started = useRef(false)
  useEffect(() => {
    if (started.current) return // StrictMode double-run would spend a second Muse Spark call
    started.current = true
    diagnose(photos).then((r) => {
      setD(r)
      setValues(Object.fromEntries(Object.entries(r.settings).map(([k, v]) => [k, String(v)])))
    }).catch((e) => setError(e.message))
  }, [photos])

  if (error) return (
    <div className="screen"><p className="eyebrow">Diagnosis</p><h2 className="title">Something went wrong</h2><p className="notice">{error}</p></div>
  )
  if (!d) return (
    <div className="screen loading">
      <p className="eyebrow">Diagnosis · in progress</p>
      <h2 className="title">Reading your photos…</h2>
      <p className="lede">Finding the damage, choosing a fix, and working out what to measure.</p>
      <div className="loader" />
      <div className="byline"><ModelTag>Muse Spark</ModelTag><ModelTag>SAM 3.1</ModelTag></div>
    </div>
  )

  const keys = [...d.measurements.map((m) => m.key), ...Object.keys(d.settings)]
  const valid = keys.every((k) => Number(values[k]) > 0)
  const shownPhotos = VIEWS.filter((v) => d.outlines[v] || d.measurements.some((m) => m.photo === v))
  const set = (k: string, v: string) => setValues({ ...values, [k]: v })
  const filled = d.measurements.filter((m) => Number(values[m.key]) > 0).length

  return (
    <div className="screen wide">
      <div className="measure-grid">
      <div>
      <p className="eyebrow">Diagnosis · <span className="accent">{d.fix_type.replace('_', ' ')}</span></p>
      <h2 className="title">{d.title}</h2>
      <p className="lede">{d.explanation}</p>
      {d.rationale && <p className="reasoning" style={{ marginTop: 6 }}>Why this fix: {d.rationale}</p>}
      <div className="byline">
        Diagnosed by <ModelTag>{d.by.diagnosis}</ModelTag> damage outlined by <ModelTag>{d.by.segmentation}</ModelTag>
      </div>

      {shownPhotos.map((view) => <DimPhoto key={view} view={view} src={urls[view]} d={d} values={values} />)}
      </div>

      <div className="measure-spec">
      <div className="section-head"><h3>Measure here</h3><span>{filled}/{d.measurements.length} entered</span></div>
      <div className="spec" style={{ borderTop: 0 }}>
        {d.measurements.map((m, i) => (
          <label className="spec-row" key={m.key}>
            <span className={`callout ${Number(values[m.key]) > 0 ? 'set' : ''}`}>{tag(m, i)}</span>
            <span className="spec-label">{m.label}<small>{m.hint}</small></span>
            <span className="spec-input">
              <input type="number" inputMode="decimal" min="0" step="0.5" placeholder={m.example ? String(m.example) : '0'}
                value={values[m.key] ?? ''} onChange={(e) => set(m.key, e.target.value)} />
              <em>mm</em>
            </span>
          </label>
        ))}
      </div>

      {scaleWarning(d, values) && <p className="notice">{scaleWarning(d, values)}</p>}

      <div className="section-head"><h3>Print settings</h3><span>editable defaults</span></div>
      <div className="spec" style={{ borderTop: 0 }}>
        {Object.keys(d.settings).map((k) => (
          <label className="spec-row" key={k}>
            <span className="callout plain">{k === 'clearance' ? '±' : k[0].toUpperCase()}</span>
            <span className="spec-label">{k[0].toUpperCase() + k.slice(1)}<small>{d.param_help[k]}</small></span>
            <span className="spec-input">
              {k === 'clearance'
                ? <select value={values[k] ?? '0.2'} onChange={(e) => set(k, e.target.value)}><option value="0.2">0.2</option><option value="0.4">0.4</option></select>
                : <input type="number" inputMode="decimal" min="0" step="0.1" value={values[k] ?? ''} onChange={(e) => set(k, e.target.value)} />}
              <em>mm</em>
            </span>
          </label>
        ))}
      </div>

      <div className="cta-bar">
        <button className="btn btn-primary btn-block" disabled={!valid}
          onClick={() => onDone(d, Object.fromEntries(keys.map((k) => [k, Number(values[k])])))}>
          Generate part <span className="arrow">→</span>
        </button>
      </div>
      </div>
      </div>
    </div>
  )
}
