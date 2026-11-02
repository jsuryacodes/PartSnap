import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { API } from './api'
import type { Done } from './Generate'
import type { Params } from './Measure'
import { ModelTag } from './ui'

const INK = 0x191917, ACCENT = 0xff5b14, PAPER = 0xfbf9f3, WOOD = 0xdcc8a6, GRAIN = 0x9a7b55

/** The part in place: seated in the damaged table from the backend (chip fill), or over a translucent table corner (corner cap). */
function Preview({ url, mateUrl, params }: { url: string; mateUrl?: string; params: Params }) {
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
    const edges = (g: THREE.BufferGeometry, color: number, opacity = 1) =>
      new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity }))

    if (!mateUrl) {
      // Table corner as a translucent block, extending past the cap so the fit reads clearly.
      const { edge_thickness: t, reach_x: rx, reach_y: ry } = params
      const tableGeo = new THREE.BoxGeometry(rx * 1.8, ry * 1.8, t)
      const table = new THREE.Mesh(tableGeo, new THREE.MeshStandardMaterial({ color: 0xc8a272, transparent: true, opacity: 0.28, depthWrite: false }))
      table.position.set(rx * 0.9, ry * 0.9, t / 2)
      table.add(edges(tableGeo, GRAIN, 0.7))
      part.add(table)
    }

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
      camera.position.copy(c).add(new THREE.Vector3(-0.7, 0.6, 0.9).multiplyScalar(size * 1.15))
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

const FACE: Record<string, string> = { '-x': 'End face A', '-y': 'End face B', '-z': 'Underside', '+z': 'Top surface' }

export default function Result({ fix, done, params, onRestart }: { fix: string; done: Done; params: Params; onRestart: () => void }) {
  const url = API + done.stl_url
  const fill = fix === 'chip_fill'
  const v = done.verify
  const gaps = v.gaps ?? []
  const partNo = (done.stl_url.match(/-([0-9a-f]{6})/)?.[1] ?? '000000').toUpperCase()
  const mm = (x: number, d = 1) => `${x.toFixed(d)} mm`
  const size = v.bbox!.map((x) => x.toFixed(1)).join(' × ')

  return (
    <div className="screen wide">
      <p className="eyebrow">Result · <span className="accent">verified</span></p>
      <h2 className="title">{fill ? 'Your missing piece is ready to print' : 'Your corner cap is ready to print'}</h2>
      <div className="result-grid">
        <div>
          <Preview url={url} mateUrl={fill && done.mate_url ? API + done.mate_url : undefined} params={params} />
          <div className="download">
            <a className="btn btn-primary btn-block" href={url} download={`partsnap-${fix.replace('_', '-')}.stl`}>Download STL <span className="arrow">↓</span></a>
            <p className="sub">STL · millimetres · {size}</p>
          </div>
          {fill && <GlueSteps clearance={params.clearance} />}
        </div>
        <div>
          <section className="sheet" aria-label="Spec sheet">
            <div className="sheet-head"><b>SPEC SHEET</b><span className="eyebrow">PS-{fill ? 'CF' : 'CC'}-{partNo}</span></div>
            {fill ? (
              <dl>
                <div className="group">Envelope</div>
                <dt>Overall size</dt><dd>{size}</dd>
                <dt>Fits edge thickness</dt><dd>{mm(params.edge_thickness)}</dd>
                <dt>Chip depth</dt><dd>{mm(params.chip_depth)}</dd>
                <dt>Clearance (nominal)</dt><dd>{mm(params.clearance, 2)}</dd>
                <div className="group">Measured fit · {gaps.length} break faces</div>
                <dt>Gap to the break, typical</dt><dd className="ok">{mm(v.gap!.typical, 2)}</dd>
                <dt>Gap, tightest / loosest</dt><dd>{v.gap!.min.toFixed(2)} / {mm(v.gap!.max, 2)}</dd>
                <dt>Overlap with the wood</dt><dd className="ok">{v.interference_volume!.toFixed(3)} mm³</dd>
                <dt>Fill ratio <span className="mono" style={{ color: 'var(--muted)', fontSize: 11 }}>of the missing volume</span></dt>
                <dd className="ok">{(v.fill_ratio! * 100).toFixed(1)}%</dd>
                <dt>Mesh</dt><dd className="ok">watertight · {v.bodies} body</dd>
              </dl>
            ) : (
              <dl>
                <div className="group">Envelope</div>
                <dt>Overall size</dt><dd>{size}</dd>
                <dt>Fits edge thickness</dt><dd>{mm(params.edge_thickness)}</dd>
                <dt>Reach, edge A / B</dt><dd>{params.reach_x.toFixed(1)} / {params.reach_y.toFixed(1)}</dd>
                <dt>Wall</dt><dd>{mm(params.wall)}</dd>
                <dt>Clearance (nominal)</dt><dd>{mm(params.clearance, 2)}</dd>
                <div className="group">Measured fit · {gaps.length} mating faces</div>
                {gaps.map((g) => [<dt key={g.face + 't'}>{FACE[g.face] ?? g.face} <span className="mono" style={{ color: 'var(--muted)', fontSize: 11 }}>{g.face}</span></dt>, <dd key={g.face} className="ok">{mm(g.gap, 2)}</dd>])}
                <dt>Overlap with table</dt><dd className="ok">{v.interference_volume!.toFixed(3)} mm³</dd>
                <dt>Mesh</dt><dd className="ok">watertight · {v.bodies} body</dd>
              </dl>
            )}
            <div className="foot byline">CAD by <ModelTag>Muse Spark Open</ModelTag><span className="mono">{done.attempts} attempt{done.attempts > 1 ? 's' : ''}</span></div>
          </section>
          <button className="btn btn-ghost btn-block" style={{ marginTop: 16 }} onClick={onRestart}>Fix something else</button>
        </div>
      </div>
    </div>
  )
}
