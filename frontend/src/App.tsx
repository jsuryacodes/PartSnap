import { useState } from 'react'
import type { Diagnosis, Photos } from './api'
import Capture from './Capture'
import Generate, { type Done } from './Generate'
import Landing from './Landing'
import Measure, { type Params } from './Measure'
import Result from './Result'
import { Footer, Logo } from './ui'

const PHASES = ['Snap', 'Measure', 'Print'] as const

export default function App() {
  const [started, setStarted] = useState(false)
  const [photos, setPhotos] = useState<Photos | null>(null)
  const [job, setJob] = useState<{ d: Diagnosis; params: Params } | null>(null)
  const [done, setDone] = useState<Done | null>(null)
  const top = () => scrollTo(0, 0)
  const restart = () => { setStarted(false); setPhotos(null); setJob(null); setDone(null); top() }

  const phase = !started ? -1 : !photos ? 0 : !job ? 1 : 2

  return (
    <>
      <header className="topbar">
        <button className="brand" onClick={restart} aria-label="PartSnap home"><Logo />PartSnap</button>
        {phase >= 0 && (
          <nav className="progress" aria-label="Progress">
            {PHASES.map((p, i) => (
              <span key={p} className={i === phase ? 'on' : i < phase ? 'done' : ''}><b>0{i + 1}</b>{p.toUpperCase()}</span>
            ))}
          </nav>
        )}
      </header>
      <main className="page">
        {!started && <Landing onStart={() => { setStarted(true); top() }} />}
        {started && !photos && <Capture onDone={(p) => { setPhotos(p); top() }} />}
        {photos && !job && <Measure photos={photos} onDone={(d, params) => { setJob({ d, params }); top() }} />}
        {job && !done && <Generate fix={job.d.fix_type} params={job.params} onDone={(d) => { setDone(d); top() }} />}
        {job && done && <Result done={done} params={job.params} onRestart={restart} />}
      </main>
      {!started && <Footer />}
    </>
  )
}
