import { useEffect, useRef, useState } from 'react'
import { checkPhoto, type Photos, type View } from './api'

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

/** Ghost frames, in the same 0–100 photo coordinates the measure overlays use. */
export function Ghost({ view }: { view: View }) {
  return (
    <svg className="overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
      {view === 'top' && <>
        <polygon points="30,35 100,35 100,100 30,100" className="ghost-fill" />
        <polyline points="30,100 30,35 100,35" className="ghost" />
      </>}
      {view === 'side' && <rect x="30" y="45" width="70" height="12" className="ghost ghost-fill" />}
      {view === 'closeup' && <circle cx="50" cy="50" r="28" className="ghost" />}
    </svg>
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
    if (!DOE || !matchMedia("(pointer: coarse)").matches) return setMode("off") // desktop: no level
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
      if (!r.ok) return setRetake(r.retake_instruction ?? 'Please retake this photo.')
      const next = { ...photos, [shot.view]: blob }
      setPhotos(next)
      if (idx + 1 < SHOTS.length) setIdx(idx + 1)
      else onDone(next as Photos)
    } catch (e) {
      setRetake(String(e))
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

  return (
    <div className="screen">
      <div className="steps">{SHOTS.map((s, i) => <span key={s.view} className={i < idx ? 'done' : i === idx ? 'now' : ''}>{s.title}</span>)}</div>
      <h2>{shot.title}</h2>
      <p>{shot.instruction}</p>

      <div className="frame">
        {camera === 'on' ? null : <div className="nocam">{camera === 'starting' ? 'Starting camera…' : 'No camera: pick a photo below'}</div>}
        <video ref={video} autoPlay playsInline muted style={{ display: camera === 'on' ? 'block' : 'none' }} />
        <Ghost view={shot.view} />
        {err !== null && <Level target={shot.target!} o={tilt.o!} ok={levelOk} err={err} />}
      </div>

      {tilt.mode === 'ask' && shot.target && <button className="secondary" onClick={tilt.enable}>Enable tilt level</button>}
      {retake && <p className="warn">{retake}</p>}

      <div className="row">
        {camera === 'on' && (
          <button onClick={snap} disabled={checking || !levelOk}>
            {checking ? 'Checking…' : levelOk ? 'Take photo' : `Tilt ${Math.round(err!)}°, level it`}
          </button>
        )}
        <label className={`button ${camera === 'on' ? 'secondary' : ''}`}>
          {camera === 'on' ? 'Upload' : checking ? 'Checking…' : 'Choose photo'}
          <input type="file" accept="image/*" capture="environment" onChange={pick} hidden disabled={checking} />
        </label>
      </div>
      <p className="by">Photo check by Muse Spark</p>
    </div>
  )
}

function Level({ target, o, ok, err }: { target: 'flat' | 'upright'; o: { beta: number; gamma: number }; ok: boolean; err: number }) {
  // Bubble moves with the tilt; centred = on target. 30° of tilt reaches the rim.
  const clamp = (v: number) => Math.max(-1, Math.min(1, v / 30))
  const dx = clamp(o.gamma) * 30
  const dy = clamp(target === 'flat' ? o.beta : o.beta - 90) * 30
  return (
    <div className={`level ${ok ? 'ok' : ''}`}>
      <svg viewBox="-40 -40 80 80" width="72" height="72">
        <circle r="36" className="rim" />
        <circle r={TOLERANCE} className="target" />
        <circle cx={dx} cy={dy} r="7" className="bubble" />
      </svg>
      <span>{Math.round(err)}°</span>
    </div>
  )
}
