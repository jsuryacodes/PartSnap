import { useState } from 'react'
import type { Photos } from './api'
import Capture from './Capture'

export default function App() {
  const [photos, setPhotos] = useState<Photos | null>(null)

  return (
    <main>
      <header><b>PartSnap</b><span>photo → printable fix</span></header>
      {!photos && <Capture onDone={setPhotos} />}
      {photos && <div className="screen"><h2>Photos checked ✓</h2></div>}
    </main>
  )
}
