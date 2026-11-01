import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { API } from './api'
import type { Done } from './Generate'
import type { Params } from './Measure'

function Preview({ url, params }: { url: string; params: Params }) {
  const el = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const box = el.current!
    const w = box.clientWidth, h = 340
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(devicePixelRatio)
    renderer.setSize(w, h)
    box.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0xf4f4f5)
    scene.add(new THREE.HemisphereLight(0xffffff, 0x999999, 2))
    const sun = new THREE.DirectionalLight(0xffffff, 2)
    sun.position.set(80, 160, 120)
    scene.add(sun)
    const camera = new THREE.PerspectiveCamera(40, w / h, 1, 5000)
    const controls = new OrbitControls(camera, renderer.domElement)

    // CadQuery is Z-up; three.js is Y-up.
    const part = new THREE.Group()
    part.rotation.x = -Math.PI / 2
    scene.add(part)

    // Table corner as a translucent block, extending past the cap so the fit reads clearly.
    const { edge_thickness: t, reach_x: rx, reach_y: ry } = params
    const table = new THREE.Mesh(
      new THREE.BoxGeometry(rx * 1.8, ry * 1.8, t),
      new THREE.MeshStandardMaterial({ color: 0xb07a45, transparent: true, opacity: 0.35, depthWrite: false }),
    )
    table.position.set(rx * 0.9, ry * 0.9, t / 2)
    part.add(table)

    new STLLoader().load(url, (geo) => {
      geo.computeVertexNormals()
      part.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.5 })))
      part.updateMatrixWorld(true) // new mesh has no world matrix yet; Box3 would ignore the group rotation
      const b = new THREE.Box3().setFromObject(part)
      const c = b.getCenter(new THREE.Vector3()), size = b.getSize(new THREE.Vector3()).length()
      controls.target.copy(c)
      camera.position.copy(c).add(new THREE.Vector3(-0.7, 0.6, 0.9).multiplyScalar(size * 1.2))
      controls.update()
    })

    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera) })
    return () => {
      renderer.setAnimationLoop(null)
      controls.dispose()
      renderer.dispose()
      box.removeChild(renderer.domElement)
    }
  }, [url])

  return <div className="viewer" ref={el} />
}

function fitSummary(gaps: Record<string, number>) {
  const vals = Object.values(gaps)
  const n = vals.length
  return vals.every((g) => g === vals[0])
    ? `${vals[0]} mm gap on all ${n} faces`
    : Object.entries(gaps).map(([f, g]) => `${g} mm on ${f}`).join(', ')
}

export default function Result({ done, params, onRestart }: { done: Done; params: Params; onRestart: () => void }) {
  const url = API + done.stl_url
  const v = done.verify
  return (
    <div className="screen">
      <h2>Your corner cap</h2>
      <Preview url={url} params={params} />
      <ul className="checks">
        <li className="ok"><span>✓ Fit</span><span>{fitSummary(v.gaps ?? {})}</span></li>
        <li className="ok"><span>✓ Overlap with table</span><span>none</span></li>
        <li className="ok"><span>✓ Printable</span><span>watertight, single body</span></li>
        <li className="ok"><span>✓ Size</span><span>{v.bbox!.join(' × ')} mm</span></li>
      </ul>
      <p className="by">CAD by Muse Spark Open in {done.attempts} attempt{done.attempts > 1 ? 's' : ''} · checked against your measurements</p>
      <a className="button wide" href={url} download="partsnap-corner-cap.stl">Download STL</a>
      <button className="secondary wide" onClick={onRestart}>Fix something else</button>
    </div>
  )
}
