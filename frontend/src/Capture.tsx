import { useEffect, useRef, useState } from 'react'
import { checkPhoto, type Photos, type View } from './api'
import { ModelTag } from './ui'

type Target = 'flat' | 'upright' | null
const SHOTS: { view: View; title: string; instruction: string; target: Target }[] = [
  { view: 'top', title: 'Top view', target: 'flat',
    instruction: 'Hold the phone flat above the corner, camera down. Line the corner up with the guide.' },
  { view: 'side', title: 'Side view', target: 'upright',
    instruction: 'Hold the phone upright, level with the tabletop. Fit the edge inside the band.' },
  { view: 'closeup', title: 'Damage close-up', target: null,
    instruction: 'Get close to the chip so it fills the circle.' },
]
const TOLERANCE = 10 // degrees

const GHOST_LABEL: Record<View, { text: string; x: number; y: number }> = {
  top: { text: 'ALIGN CORNER', x: 30, y: 35 },
  side: { text: 'TABLE EDGE', x: 30, y: 45 },
  closeup: { text: 'DAMAGE', x: 50, y: 22 },
}

/** Ghost frames, in the same 0–100 photo coordinates the measure overlays use. */
export function Ghost({ view }: { view: View }) {
  const l = GHOST_LABEL[view]
  return (
    <>
      <svg className="overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
        {view === 'top' && <>
          <polygon points="30,35 100,35 100,100 30,100" className="ghost-fill" />
          <polyline points="30,100 30,35 100,35" className="ghost" />
        </>}
        {view === 'side' && <>
          <rect x="30" y="45" width="70" height="12" className="ghost-fill" />
          <rect x="30" y="45" width="70" height="12" className="ghost" />
        </>}
        {view === 'closeup' && <circle cx="50" cy="50" r="28" className="ghost" />}
      </svg>
      <span className="ghost-label" style={{ left: `${l.x}%`, top: `${l.y}%` }}>{l.text}</span>
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

async function toJpeg(src: CanvasImageSource, w: number, h: number): Promise<Blob> {
  const s = Math.min(1, 1600 / Math.max(w, h))
  const c = document.createElement('canvas')
  c.width = Math.round(w * s)
  c.height = Math.round(h * s)
  c.getContext('2d')!.drawImage(src, 0, 0, c.width, c.height)
  return new Promise((ok) => c.toBlob((b) => ok(b!), 'image/jpeg', 0.85))
}

export default function Capture({ onDone }: { onDone: (p: Photos) => void }) {
  const [idx, setIdx] = useState(0)
  const [photos, setPhotos] = useState<Partial<Photos>>({})
  // ponytail: thumbnail object URLs are never revoked; three small images per session
  const [thumbs, setThumbs] = useState<Partial<Record<View, string>>>({})
  const [camera, setCamera] = useState<'starting' | 'on' | 'off'>('starting')
  const [checking, setChecking] = useState(false)
  const [retake, setRetake] = useState<string | null>(null)
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

  async function submit(blob: Blob) {
    setChecking(true)
    setRetake(null)
    try {
      const r = await checkPhoto(shot.view, blob)
      if (!r.ok) return setRetake([r.retake_instruction ?? 'Please retake this photo.', r.rationale].filter(Boolean).join(' '))
      const next = { ...photos, [shot.view]: blob }
      setPhotos(next)
      setThumbs((t) => ({ ...t, [shot.view]: URL.createObjectURL(blob) }))
      if (idx + 1 < SHOTS.length) setIdx(idx + 1)
      else onDone(next as Photos)
    } catch (e) {
      setRetake((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  async function snap() {
    const v = video.current!
    submit(await toJpeg(v, v.videoWidth, v.videoHeight))
  }

  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    const bmp = await createImageBitmap(f)
    submit(await toJpeg(bmp, bmp.width, bmp.height))
  }

  const hint = checking ? 'Inspecting photo…'
    : err !== null && !levelOk ? `Tilt ${Math.round(err)}° · level the phone`
    : err !== null ? 'Level ✓ · take the shot'
    : camera === 'off' ? 'No camera found · upload a photo instead' : ''

  return (
    <div className="screen">
      <div key={shot.view} style={{ animation: 'rise .4s var(--ease) both' }}>
      <div className="shotbar">
        <p className="eyebrow">Shot <span className="accent">{idx + 1}</span> / {SHOTS.length}</p>
        <p className="eyebrow">{shot.target === 'flat' ? 'Target 0° · flat' : shot.target === 'upright' ? 'Target 90° · upright' : 'Any angle'}</p>
      </div>
      <h2 className="title">{shot.title}</h2>
      <p className="lede">{shot.instruction}</p>
      </div>

      <div className="viewport">
        {camera !== 'on' && <div className="placeholder">{camera === 'starting' ? 'Starting camera…' : 'Camera unavailable'}</div>}
        <video ref={video} autoPlay playsInline muted style={{ display: camera === 'on' ? 'block' : 'none' }} />
        <Ghost view={shot.view} />
        {err !== null && <Level target={shot.target!} o={tilt.o!} ok={levelOk} err={err} />}
        {checking && <div className="scan"><span>Inspecting · Muse Spark</span></div>}
      </div>

      {tilt.mode === 'ask' && shot.target && (
        <button className="btn btn-ghost btn-block" style={{ marginTop: 12 }} onClick={tilt.enable}>Enable tilt level</button>
      )}
      {retake && <p className="notice">{retake}</p>}

      <div className="shutter-row">
        <div className="thumbs" aria-label="Shots taken">
          {SHOTS.map((s, i) => (
            <span key={s.view} className={thumbs[s.view] ? 'done' : i === idx ? 'now' : ''}
              style={thumbs[s.view] ? { backgroundImage: `url(${thumbs[s.view]})` } : undefined}>{i + 1}</span>
          ))}
        </div>
        {camera === 'on'
          ? <button className="shutter" onClick={snap} disabled={checking || !levelOk} aria-label="Take photo" />
          : <label className="btn btn-primary" aria-disabled={checking}>
              {checking ? 'Checking…' : 'Choose photo'}
              <input type="file" accept="image/*" capture="environment" onChange={pick} hidden disabled={checking} />
            </label>}
        {camera === 'on'
          ? <label className="linkbtn upload">Upload<input type="file" accept="image/*" onChange={pick} hidden disabled={checking} /></label>
          : <span />}
      </div>
      <p className={`hint ${err !== null && !levelOk ? 'warn' : ''}`}>{hint}</p>

      <div className="byline" style={{ justifyContent: 'center' }}>Each photo checked by <ModelTag>Muse Spark</ModelTag></div>
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
