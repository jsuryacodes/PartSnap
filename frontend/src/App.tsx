import { useState } from 'react'
import type { Diagnosis, Photos } from './api'
import Capture from './Capture'
import Measure, { type Params } from './Measure'

export default function App() {
  const [photos, setPhotos] = useState<Photos | null>(null)
  const [job, setJob] = useState<{ d: Diagnosis; params: Params } | null>(null)

  return (
    <main>
      <header><b>PartSnap</b><span>photo → printable fix</span></header>
      {!photos && <Capture onDone={setPhotos} />}
      {photos && !job && <Measure photos={photos} onDone={(d, params) => setJob({ d, params })} />}
      {job && <div className="screen"><pre>{JSON.stringify(job.params, null, 2)}</pre></div>}
    </main>
  )
}
