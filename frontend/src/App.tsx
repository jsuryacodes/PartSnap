import { useState } from 'react'
import type { Diagnosis, Photos } from './api'
import Capture from './Capture'
import Generate, { type Done } from './Generate'
import Measure, { type Params } from './Measure'
import Result from './Result'

export default function App() {
  const [photos, setPhotos] = useState<Photos | null>(null)
  const [job, setJob] = useState<{ d: Diagnosis; params: Params } | null>(null)
  const [done, setDone] = useState<Done | null>(null)
  const restart = () => { setPhotos(null); setJob(null); setDone(null) }

  return (
    <main>
      <header><b>PartSnap</b><span>photo → printable fix</span></header>
      {!photos && <Capture onDone={setPhotos} />}
      {photos && !job && <Measure photos={photos} onDone={(d, params) => setJob({ d, params })} />}
      {job && !done && <Generate fix={job.d.fix_type} params={job.params} onDone={setDone} />}
      {job && done && <Result done={done} params={job.params} onRestart={restart} />}
    </main>
  )
}
