import { useEffect, useRef, useState } from 'react'
import { checkPhoto, type Photos, type View } from './api'
import { ModelTag } from './ui'

type Target = 'flat' | 'upright' | null
const SHOTS: { view: View; title: string; instruction: string; target: Target; check: boolean }[] = [
  { view: 'top', title: 'Top view', target: 'flat', check: true,
    instruction: 'Hold the phone flat, straight above the chip, camera down. Table edge along the guide line, chip in the middle.' },
  { view: 'side', title: 'Front view', target: 'upright', check: true,
    instruction: 'Hold the phone upright, level with the tabletop, facing the front of the edge. Top edge along the guide line, chip in the middle.' },
  { view: 'closeup', title: 'Context', target: null, check: false,
    instruction: 'Step back and take the whole table edge with the chip in view. Not checked: it only helps the diagnosis.' },
]
const TOLERANCE = 10 // degrees
const USE_ANYWAY_AFTER = 2 // failed checks

const GHOST_LABEL: Record<View, { text: string; x: number; y: number }> = {
  top: { text: 'TABLE EDGE · CHIP HERE', x: 50, y: 66 },
  side: { text: 'TOP EDGE · CHIP HERE', x: 50, y: 46 },
  closeup: { text: 'WHOLE EDGE IN VIEW', x: 50, y: 22 },
}

/** Ghost frames, in the same 0–100 photo coordinates the measure overlays use. */
export function Ghost({ view }: { view: View }) {
  const l = GHOST_LABEL[view]
  return (
    <>
      <svg className="overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
        {view === 'top' && <>
          <rect x="0" y="0" width="100" height="78" className="ghost-fill" />
          <line x1="0" y1="78" x2="100" y2="78" className="ghost" />
          <ellipse cx="50" cy="74" rx="14" ry="6" className="ghost" />
        </>}
        {view === 'side' && <>
          <rect x="0" y="48" width="100" height="22" className="ghost-fill" />
          <line x1="0" y1="48" x2="100" y2="48" className="ghost" />
          <ellipse cx="50" cy="52" rx="14" ry="5" className="ghost" />
        </>}
      </svg>
      <span className="ghost-label" style={{ left: `${l.x}%`, top: `${l.y}%`, transform: 'translate(-50%, -140%)' }}>{l.text}</span>
      <i className="vf tl" /><i className="vf tr" /><i className="vf bl" /><i className="vf br" />
    </>
  )
}

type LevelMode = 'pending' | 'ask' | 'on' | 'off'

function useTilt() {
  const [mode, setMode] = useState<LevelMode>('pending')
  const [o, setO] = useState<{ beta: number; gamma: number } | null>(null)
  const DOE = (window as any).DeviceOrientationEvent

  const listen = () => {
    const h = (e: DeviceOrientationEvent) => {
      if (e.beta === null || e.gamma === null) return
      setO({ beta: e.beta, gamma: e.gamma })
      setMode('on')
    }
    window.addEventListener('deviceorientation', h)
    // Desktops either never fire the event or fire it with nulls: no level there.
    setTimeout(() => setMode((m) => (m === 'on' ? m : 'off')), 1500)
    return () => window.removeEventListener('deviceorientation', h)
  }

  useEffect(() => {
    if (!DOE || !matchMedia('(pointer: coarse)').matches) return setMode('off') // desktop: no level
    if (typeof DOE.requestPermission === 'function') return setMode('ask') // iOS: needs a tap
    return listen()
  }, [])

  const enable = async () => {
    try {
      if ((await DOE.requestPermission()) === 'granted') listen()
      else setMode('off')
    } catch { setMode('off') }
  }
  return { mode, o, enable }
}

function tiltError(target: Target, o: { beta: number; gamma: number }) {
  if (target === 'flat') return Math.max(Math.abs(o.beta), Math.abs(o.gamma))
  if (target === 'upright') return Math.abs(o.beta - 90)
  return 0
}

export async function toJpeg(src: CanvasImageSource, w: number, h: number): Promise<Blob> {
  const s = Math.min(1, 1600 / Math.max(w, h))
  const c = document.createElement('canvas')
  c.width = Math.round(w * s)
  c.height = Math.round(h * s)
  c.getContext('2d')!.drawImage(src, 0, 0, c.width, c.height)
  return new Promise((ok) => c.toBlob((b) => ok(b!), 'image/jpeg', 0.85))
}

type Check = Awaited<ReturnType<typeof checkPhoto>>

export default function Capture({ onDone, onCancel }: { onDone: (p: Photos) => void; onCancel: () => void }) {
  const [idx, setIdx] = useState(0)
  const [photos, setPhotos] = useState<Partial<Photos>>({})
  // ponytail: thumbnail object URLs are never revoked; three small images per session
  const [thumbs, setThumbs] = useState<Partial<Record<View, string>>>({})
  const [camera, setCamera] = useState<'starting' | 'on' | 'off'>('starting')
  const [pending, setPending] = useState<{ blob: Blob; url: string } | null>(null) // taken, not yet accepted
  const [checking, setChecking] = useState(false)
  const [check, setCheck] = useState<Check | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [fails, setFails] = useState(0) // failed checks for this shot
  const video = useRef<HTMLVideoElement>(null)
  const tilt = useTilt()
  const shot = SHOTS[idx]

  useEffect(() => {
    let stream: MediaStream | undefined
    navigator.mediaDevices?.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 } }, audio: false })
      .then((s) => { stream = s; video.current!.srcObject = s; setCamera('on') })
      .catch(() => setCamera('off'))
    return () => stream?.getTracks().forEach((t) => t.stop())
  }, [])

  const err = tilt.mode === 'on' && tilt.o && shot.target ? tiltError(shot.target, tilt.o) : null
  const levelOk = err === null || err <= TOLERANCE

  function accept(blob: Blob) {
    const next = { ...photos, [shot.view]: blob }
    setPhotos(next)
    setThumbs((t) => ({ ...t, [shot.view]: URL.createObjectURL(blob) }))
    setPending(null); setCheck(null); setError(null); setFails(0)
    if (idx + 1 < SHOTS.length) setIdx(idx + 1)
    else onDone(next as Photos)
  }

  function took(blob: Blob) {
    if (!shot.check) return accept(blob)
    setPending({ blob, url: URL.createObjectURL(blob) }); setCheck(null); setError(null)
  }

  function retake() {
    if (pending) URL.revokeObjectURL(pending.url)
    setPending(null); setCheck(null); setError(null)
  }

  async function runCheck() {
    setChecking(true); setError(null)
    try {
      const r = await checkPhoto(shot.view, pending!.blob)
      setCheck(r)
      if (!r.ok) setFails((n) => n + 1)
    } catch (e) {
      setError((e as Error).message)
      setFails((n) => n + 1)
    } finally {
      setChecking(false)
    }
  }

  async function snap() {
    const v = video.current!
    took(await toJpeg(v, v.videoWidth, v.videoHeight))
  }

  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    const bmp = await createImageBitmap(f)
    took(await toJpeg(bmp, bmp.width, bmp.height))
  }

  const hint = pending ? (checking ? 'Muse Spark Open is checking the photo…' : '')
    : err !== null && !levelOk ? `Tilt ${Math.round(err)}° · level the phone`
    : err !== null ? 'Level ✓ · take the shot'
    : camera === 'off' ? 'No camera found · upload a photo instead' : ''

  return (
    <div className="screen">
      <div key={shot.view} style={{ animation: 'rise .4s var(--ease) both' }}>
      <div className="shotbar">
        <p className="eyebrow">Shot <span className="accent">{idx + 1}</span> / {SHOTS.length}</p>
        <button className="linkbtn" onClick={onCancel}>Cancel</button>
      </div>
      <h2 className="title">{shot.title}</h2>
      <p className="lede">{shot.instruction}</p>
      </div>

      <div className="viewport">
        {camera !== 'on' && !pending && <div className="placeholder">{camera === 'starting' ? 'Starting camera…' : 'Camera unavailable'}</div>}
        <video ref={video} autoPlay playsInline muted style={{ display: camera === 'on' && !pending ? 'block' : 'none' }} />
        {pending && <img src={pending.url} alt={`${shot.title}, taken`} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
        {!pending && <Ghost view={shot.view} />}
        {!pending && err !== null && <Level target={shot.target!} o={tilt.o!} ok={levelOk} err={err} />}
        {checking && <div className="scan"><span>Checking · Muse Spark Open</span></div>}
      </div>

      {!pending && tilt.mode === 'ask' && shot.target && (
        <button className="btn btn-ghost btn-block" style={{ marginTop: 12 }} onClick={tilt.enable}>Enable tilt level</button>
      )}
      {error && <p className="notice">{error}</p>}
      {check && (
        <div className={check.ok ? 'reasoning' : 'notice'} style={{ marginTop: 12 }}>
          <strong>{check.ok ? 'Looks good. ' : `${check.retake_instruction ?? 'Please retake this photo.'} `}</strong>{check.rationale}
          {check.reasoning && (
            <details className="panel" style={{ marginTop: 8 }}>
              <summary>Spark Open's reasoning</summary>
              <p className="reasoning" style={{ whiteSpace: 'pre-wrap' }}>{check.reasoning}</p>
            </details>
          )}
        </div>
      )}

      {pending ? (
        <div className="cta-bar" style={{ display: 'grid', gap: 10 }}>
          {check?.ok
            ? <button className="btn btn-primary btn-block" onClick={() => accept(pending.blob)}>Next <span className="arrow">→</span></button>
            : (check || error)
              ? <button className="btn btn-primary btn-block" onClick={retake}>Retake</button>
              : <button className="btn btn-primary btn-block" onClick={runCheck} disabled={checking}>{checking ? 'Checking…' : 'Check photo'}</button>}
          {(check || error) && !check?.ok && fails < USE_ANYWAY_AFTER && !checking &&
            <button className="btn btn-ghost btn-block" onClick={runCheck}>Check again</button>}
          {!check?.ok && fails >= USE_ANYWAY_AFTER && !checking &&
            <button className="btn btn-ghost btn-block" onClick={() => accept(pending.blob)}>Use anyway <span className="arrow">→</span></button>}
          {!check && !error && <button className="btn btn-ghost btn-block" onClick={retake} disabled={checking}>Retake</button>}
        </div>
      ) : (
        <div className="shutter-row">
          <div className="thumbs" aria-label="Shots taken">
            {SHOTS.map((s, i) => (
              <span key={s.view} className={thumbs[s.view] ? 'done' : i === idx ? 'now' : ''}
                style={thumbs[s.view] ? { backgroundImage: `url(${thumbs[s.view]})` } : undefined}>{i + 1}</span>
            ))}
          </div>
          {camera === 'on'
            ? <button className="shutter" onClick={snap} disabled={!levelOk} aria-label="Take photo" />
            : <label className="btn btn-primary">
                Choose photo
                <input type="file" accept="image/*" capture="environment" onChange={pick} hidden />
              </label>}
          {camera === 'on'
            ? <label className="linkbtn upload">Upload<input type="file" accept="image/*" onChange={pick} hidden /></label>
            : <span />}
        </div>
      )}
      <p className={`hint ${err !== null && !levelOk && !pending ? 'warn' : ''}`}>{hint}</p>

      <div className="byline" style={{ justifyContent: 'center' }}>
        {shot.check ? <>Checked by <ModelTag>Muse Spark Open</ModelTag></> : 'Not checked · used for the diagnosis only'}
      </div>
    </div>
  )
}

function Level({ target, o, ok, err }: { target: 'flat' | 'upright'; o: { beta: number; gamma: number }; ok: boolean; err: number }) {
  // Bubble moves with the tilt; centred = on target. 30° of tilt reaches the rim.
  const R = 34
  const clamp = (v: number) => Math.max(-1, Math.min(1, v / 30))
  const dx = clamp(o.gamma) * (R - 7)
  const dy = clamp(target === 'flat' ? o.beta : o.beta - 90) * (R - 7)
  const tol = (TOLERANCE / 30) * (R - 7) + 7
  return (
    <div className={`level ${ok ? 'ok' : ''}`} role="status" aria-label={`Tilt ${Math.round(err)} degrees`}>
      <svg viewBox="-40 -40 80 80" width="80" height="80">
        <circle r={R} className="ring" />
        {Array.from({ length: 12 }, (_, i) => {
          const a = (i * Math.PI) / 6, r1 = i % 3 === 0 ? R - 6 : R - 3
          return <line key={i} className="tick" x1={Math.cos(a) * r1} y1={Math.sin(a) * r1} x2={Math.cos(a) * R} y2={Math.sin(a) * R} />
        })}
        <line className="cross" x1={-R} x2={R} y1="0" y2="0" />
        <line className="cross" y1={-R} y2={R} x1="0" x2="0" />
        <circle r={tol} className="tol" />
        <circle cx={dx} cy={dy} r="7" className="bubble" />
      </svg>
      <span className="read">{ok ? 'LEVEL' : `${String(Math.round(err)).padStart(2, '0')}°`}</span>
    </div>
  )
}
