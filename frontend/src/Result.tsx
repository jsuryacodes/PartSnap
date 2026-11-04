import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { API } from './api'
import type { Done } from './Generate'
import type { Params } from './Measure'
import { ModelTag } from './ui'

const INK = 0x191917, ACCENT = 0xff5b14, PAPER = 0xfbf9f3, WOOD = 0xdcc8a6, GRAIN = 0x9a7b55

/** The part seated in the damaged table, both from the backend. The chip_fill frame is z-down (tabletop at z = 0, the
 * table below it), so it turns the other way from CadQuery's usual z-up to sit tabletop-up in three.js. */
function Preview({ url, mateUrl }: { url: string; mateUrl?: string }) {
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
    sun.position.set(80, 160, -120)
    scene.add(sun)
    const camera = new THREE.PerspectiveCamera(35, w / h, 0.1, 5000)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    const part = new THREE.Group()
    part.rotation.x = Math.PI / 2 // z-down -> y-up; the front face (y = 0) then faces the camera at -z
    scene.add(part)
    const edges = (g: THREE.BufferGeometry, color: number) =>
      new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color }))

    let alive = true
    const loader = new STLLoader()
    Promise.all([loader.loadAsync(url), mateUrl ? loader.loadAsync(mateUrl) : null]).then(([geo, mate]) => {
      if (!alive) return
      if (mate) {
        const table = new THREE.Mesh(mate, new THREE.MeshStandardMaterial({ color: WOOD, roughness: 0.95 }))
        table.add(edges(mate, GRAIN))
        part.add(table)
      }
      geo.computeVertexNormals()
      const piece = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: ACCENT, roughness: 0.55, metalness: 0 }))
      piece.add(edges(geo, INK))
      part.add(piece)
      part.updateMatrixWorld(true) // new meshes have no world matrix yet; Box3 would ignore the group rotation
      const all = new THREE.Box3().setFromObject(part)
      // Chip fill frames the piece and the corner around it; the rest of the table runs out of view.
      const b = mate ? new THREE.Box3().setFromObject(piece) : all
      const c = b.getCenter(new THREE.Vector3()), size = b.getSize(new THREE.Vector3()).length() * (mate ? 3 : 1)

      // Drawing-sheet grid under the part, 10 mm cells.
      const span = Math.ceil((size * 2.5) / 10) * 10
      const grid = new THREE.GridHelper(span, span / 10, 0xb9b09c, 0xddd5c4)
      grid.position.set(c.x, all.min.y - 0.01, c.z)
      scene.add(grid)

      controls.minDistance = size * 0.5 // keep wheel/pinch zoom from diving inside the part
      controls.maxDistance = size * 4
      controls.target.copy(c)
      camera.position.copy(c).add(new THREE.Vector3(0.45, 0.75, -0.9).multiplyScalar(size * 1.15))
      controls.update()
    })

    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera) })
    return () => {
      alive = false
      renderer.setAnimationLoop(null)
      controls.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [url, mateUrl])

  return <div className="viewer" ref={el}><span className="caption">Iso view · drag to orbit · grid 10 mm</span></div>
}

function GlueSteps({ clearance }: { clearance: number }) {
  return (
    <section className="howto" aria-label="Glue it in">
      <div className="section-head"><h3>Glue it in</h3><span>4 steps</span></div>
      <ol>
        <li><span><b>Print it top face down.</b> Lay it on the face that sits flush with the tabletop, so the smoothest surface is the one on show. PLA or PETG, 40% infill or more.</span></li>
        <li><span><b>Dry-fit it.</b> It should slide into the chip with a hair of play all round ({clearance.toFixed(1)} mm). Sand a high spot rather than force it.</span></li>
        <li><span><b>Glue it in place.</b> Two-part epoxy or CA (super) glue on the break; PVA wood glue won’t grip the plastic. Press it flush, tape it down and leave it to cure.</span></li>
        <li><span><b>Finish.</b> Sand the seam flush, then fill and paint or stain it to match the table.</span></li>
      </ol>
    </section>
  )
}

export default function Result({ done, params, onRestart }: { done: Done; params: Params; onRestart: () => void }) {
  const v = done.verify
  const design = done.stls.find((s) => s.clearance === params.clearance) ?? done.stls[0]
  const partNo = (design.url.match(/-([0-9a-f]{6})/)?.[1] ?? '000000').toUpperCase()
  const mm = (x: number, d = 1) => `${x.toFixed(d)} mm`
  const size = v.bbox!.map((x) => x.toFixed(1)).join(' × ')

  return (
    <div className="screen wide">
      <p className="eyebrow">Result · <span className="accent">verified</span></p>
      <h2 className="title">Your missing piece is ready to print</h2>
      {done.overridden && <p className="notice">Downloaded despite the reviewer's concerns (recorded in the agent log): {done.review?.notes.join(' ')}</p>}
      <div className="result-grid">
        <div>
          <Preview url={API + design.url} mateUrl={done.mate_url ? API + done.mate_url : undefined} />
          <div className="download">
            {done.stls.map((s) => (
              <a key={s.clearance} className={`btn btn-block ${s.clearance === params.clearance ? 'btn-primary' : 'btn-ghost'}`}
                style={{ marginBottom: 8 }} href={API + s.url} download={`partsnap-chip-fill-${s.clearance.toFixed(1)}mm.stl`}>
                Download STL · {s.clearance.toFixed(1)} mm clearance{s.clearance > params.clearance ? ' (looser)' : s.clearance < params.clearance ? ' (snugger)' : ''} <span className="arrow">↓</span>
              </a>
            ))}
            <p className="sub">STL · millimetres · {size} · lies tabletop face down, no supports</p>
          </div>
          <GlueSteps clearance={params.clearance} />
        </div>
        <div>
          <section className="sheet" aria-label="Spec sheet">
            <div className="sheet-head"><b>SPEC SHEET</b><span className="eyebrow">PS-CF-{partNo}</span></div>
            <dl>
              <div className="group">Measured</div>
              <dt>Chip length</dt><dd>{mm(params.edge_length_mm)}</dd>
              <dt>Depth on top / front</dt><dd>{params.top_depth_mm.toFixed(1)} / {mm(params.front_depth_mm)}</dd>
              <div className="group">Piece · {params.clearance.toFixed(1)} mm clearance</div>
              <dt>Overall size</dt><dd>{size} mm</dd>
              {done.trimmed_mm !== undefined && <><dt>Thin ends trimmed</dt><dd>{mm(done.trimmed_mm, 2)}</dd></>}
              {v.min_thickness !== undefined && <><dt>Thinnest section</dt><dd className="ok">{mm(v.min_thickness, 2)}</dd></>}
              {v.gap && <>
                <dt>Gap to the break, typical</dt><dd className="ok">{mm(v.gap.typical, 3)}</dd>
                <dt>Gap, tightest / loosest</dt><dd>{v.gap.min.toFixed(3)} / {mm(v.gap.max, 3)}</dd>
              </>}
              <dt>Overlap with the table</dt><dd className="ok">{v.interference_volume!.toFixed(3)} mm³</dd>
              <dt>Checks</dt><dd className="ok">{v.checks.filter((c) => c.ok).length}/{v.checks.length} passed</dd>
            </dl>
            {done.rationale && <p className="reasoning" style={{ padding: '8px 12px', fontSize: 14 }}>“{done.rationale}”</p>}
            <div className="foot byline">CAD by <ModelTag>{done.by}</ModelTag><span className="mono">{done.attempts} attempt{done.attempts > 1 ? 's' : ''}</span>
              {done.review && <>reviewed by <ModelTag>{done.review.by}</ModelTag><span className="mono">{done.review.verdict}</span></>}</div>
          </section>
          <button className="btn btn-ghost btn-block" style={{ marginTop: 16 }} onClick={onRestart}>Fix something else</button>
        </div>
      </div>
    </div>
  )
}
