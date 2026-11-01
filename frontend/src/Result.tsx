import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { API } from './api'
import type { Done } from './Generate'
import type { Params } from './Measure'
import { ModelTag } from './ui'

const INK = 0x191917, ACCENT = 0xff5b14, PAPER = 0xfbf9f3

function Preview({ url, params }: { url: string; params: Params }) {
  const el = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const box = el.current!
    const w = box.clientWidth, h = Math.round(Math.min(420, Math.max(300, w * 0.75)))
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(devicePixelRatio)
    renderer.setSize(w, h)
    box.prepend(renderer.domElement)

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(PAPER)
    scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b09c, 2.2))
    const sun = new THREE.DirectionalLight(0xffffff, 1.6)
    sun.position.set(-80, 160, 120)
    scene.add(sun)
    const camera = new THREE.PerspectiveCamera(35, w / h, 1, 5000)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    // CadQuery is Z-up; three.js is Y-up.
    const part = new THREE.Group()
    part.rotation.x = -Math.PI / 2
    scene.add(part)

    // Table corner as a translucent block, extending past the cap so the fit reads clearly.
    const { edge_thickness: t, reach_x: rx, reach_y: ry } = params
    const tableGeo = new THREE.BoxGeometry(rx * 1.8, ry * 1.8, t)
    const table = new THREE.Mesh(tableGeo, new THREE.MeshStandardMaterial({ color: 0xc8a272, transparent: true, opacity: 0.28, depthWrite: false }))
    table.position.set(rx * 0.9, ry * 0.9, t / 2)
    table.add(new THREE.LineSegments(new THREE.EdgesGeometry(tableGeo), new THREE.LineBasicMaterial({ color: 0x9a7b55, transparent: true, opacity: 0.7 })))
    part.add(table)

    new STLLoader().load(url, (geo) => {
      geo.computeVertexNormals()
      const cap = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: ACCENT, roughness: 0.55, metalness: 0 }))
      cap.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 30), new THREE.LineBasicMaterial({ color: INK })))
      part.add(cap)
      part.updateMatrixWorld(true) // new mesh has no world matrix yet; Box3 would ignore the group rotation
      const b = new THREE.Box3().setFromObject(part)
      const c = b.getCenter(new THREE.Vector3()), size = b.getSize(new THREE.Vector3()).length()

      // Drawing-sheet grid under the part, 10 mm cells.
      const span = Math.ceil((size * 2.5) / 10) * 10
      const grid = new THREE.GridHelper(span, span / 10, 0xb9b09c, 0xddd5c4)
      grid.position.set(c.x, b.min.y - 0.01, c.z)
      scene.add(grid)

      controls.minDistance = size * 0.5 // keep wheel/pinch zoom from diving inside the part
      controls.maxDistance = size * 4
      controls.target.copy(c)
      camera.position.copy(c).add(new THREE.Vector3(-0.7, 0.6, 0.9).multiplyScalar(size * 1.15))
      controls.update()
    })

    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera) })
    return () => {
      renderer.setAnimationLoop(null)
      controls.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [url])

  return <div className="viewer" ref={el}><span className="caption">Iso view · drag to orbit · grid 10 mm</span></div>
}

const FACE: Record<string, string> = { '-x': 'End face A', '-y': 'End face B', '-z': 'Underside', '+z': 'Top surface' }

export default function Result({ done, params, onRestart }: { done: Done; params: Params; onRestart: () => void }) {
  const url = API + done.stl_url
  const v = done.verify
  const gaps = Object.entries(v.gaps ?? {})
  const partNo = (done.stl_url.match(/-([0-9a-f]{6})/)?.[1] ?? '000000').toUpperCase()
  const mm = (x: number, d = 1) => `${x.toFixed(d)} mm`

  return (
    <div className="screen wide">
      <p className="eyebrow">Result · <span className="accent">verified</span></p>
      <h2 className="title">Your corner cap is ready to print</h2>
      <div className="result-grid">
        <div>
          <Preview url={url} params={params} />
          <div className="download">
            <a className="btn btn-primary btn-block" href={url} download="partsnap-corner-cap.stl">Download STL <span className="arrow">↓</span></a>
            <p className="sub">STL · millimetres · {v.bbox!.map((x) => x.toFixed(1)).join(" × ")}</p>
            <button className="btn btn-ghost btn-block" style={{ marginTop: 16 }} onClick={onRestart}>Fix something else</button>
          </div>
        </div>
        <section className="sheet" aria-label="Spec sheet">
          <div className="sheet-head"><b>SPEC SHEET</b><span className="eyebrow">PS-CC-{partNo}</span></div>
          <dl>
            <div className="group">Envelope</div>
            <dt>Overall size</dt><dd>{v.bbox!.map((x) => x.toFixed(1)).join(' × ')}</dd>
            <dt>Fits edge thickness</dt><dd>{mm(params.edge_thickness)}</dd>
            <dt>Reach, edge A / B</dt><dd>{params.reach_x.toFixed(1)} / {params.reach_y.toFixed(1)}</dd>
            <dt>Wall</dt><dd>{mm(params.wall)}</dd>
            <dt>Clearance (nominal)</dt><dd>{mm(params.clearance, 2)}</dd>
            <div className="group">Measured fit · {gaps.length} mating faces</div>
            {gaps.map(([f, g]) => [<dt key={f + 't'}>{FACE[f] ?? f} <span className="mono" style={{ color: 'var(--muted)', fontSize: 11 }}>{f}</span></dt>, <dd key={f} className="ok">{mm(g, 2)}</dd>])}
            <dt>Overlap with table</dt><dd className="ok">{v.interference_volume!.toFixed(3)} mm³</dd>
            <dt>Mesh</dt><dd className="ok">watertight · {v.bodies} body</dd>
          </dl>
          <div className="foot byline">CAD by <ModelTag>Muse Spark Open</ModelTag><span className="mono">{done.attempts} attempt{done.attempts > 1 ? 's' : ''}</span></div>
        </section>
      </div>
    </div>
  )
}
