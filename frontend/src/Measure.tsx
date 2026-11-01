import { useEffect, useRef, useState } from 'react'
import { diagnose, type Diagnosis, type Photos, type View } from './api'

export type Params = Record<string, number>

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
    }).catch((e) => setError(String(e)))
  }, [photos])

  if (error) return <div className="screen"><p className="warn">{error}</p></div>
  if (!d) return <div className="screen"><h2>Diagnosing…</h2><p className="by">Muse Spark is looking at your photos</p></div>

  const keys = [...d.measurements.map((m) => m.key), ...Object.keys(d.settings)]
  const valid = keys.every((k) => Number(values[k]) > 0)
  const shownPhotos = [...new Set([d.damage?.photo, ...d.measurements.map((m) => m.photo)].filter(Boolean))] as View[]
  const set = (k: string, v: string) => setValues({ ...values, [k]: v })

  return (
    <div className="screen">
      <h2>{d.title}</h2>
      <p>{d.explanation}</p>
      <p className="by">Diagnosed by {d.by.diagnosis} · damage outlined by {d.by.segmentation}</p>

      {shownPhotos.map((view) => (
        <div className="frame" key={view}>
          <img src={urls[view]} alt={view} />
          <svg className="overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
            {d.damage?.photo === view && <polygon points={d.damage.polygon.map((p) => p.join(',')).join(' ')} className="damage" />}
            {d.measurements.filter((m) => m.photo === view).map((m, i) => (
              <line key={m.key} x1={m.line[0][0]} y1={m.line[0][1]} x2={m.line[1][0]} y2={m.line[1][1]} className={`measure m${i}`} />
            ))}
          </svg>
          {d.measurements.filter((m) => m.photo === view).map((m) => {
            const [[x1, y1], [x2, y2]] = m.line
            const n = d.measurements.indexOf(m) + 1
            return <span key={m.key} className="tag" style={{ left: `${((x1 + x2) / 2) * 100}%`, top: `${((y1 + y2) / 2) * 100}%` }}>{n}</span>
          })}
        </div>
      ))}

      <h3>Measure here</h3>
      {d.measurements.map((m, i) => (
        <label className="field" key={m.key}>
          <span><b className="tag inline">{i + 1}</b> {m.label}<small>{m.hint}</small></span>
          <span className="mm"><input type="number" inputMode="decimal" min="0" step="0.5" placeholder={m.example ? `e.g. ${m.example}` : ''}
            value={values[m.key] ?? ''} onChange={(e) => set(m.key, e.target.value)} /> mm</span>
        </label>
      ))}

      <h3>Print settings</h3>
      {Object.keys(d.settings).map((k) => (
        <label className="field" key={k}>
          <span>{k}<small>{d.param_help[k]}</small></span>
          <span className="mm"><input type="number" inputMode="decimal" min="0" step="0.1" value={values[k] ?? ''} onChange={(e) => set(k, e.target.value)} /> mm</span>
        </label>
      ))}

      <button className="wide" disabled={!valid} onClick={() => onDone(d, Object.fromEntries(keys.map((k) => [k, Number(values[k])])))}>
        Generate fix
      </button>
    </div>
  )
}
