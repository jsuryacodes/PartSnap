import { useEffect, useRef, useState, type Ref } from 'react'
import * as THREE from 'three'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import type { VerifyResult } from './api'
import { Checks } from './Generate'
import HIW from './hiw.json'
import { ArrowDefs, ModelTag } from './ui'

type V3 = [number, number, number]
type Pt = [number, number]
const PARTS = ['table', 'piece', 'prism_top', 'prism_side'] as const
type Geos = Record<(typeof PARTS)[number], THREE.BufferGeometry>

// The app's default missing piece: the mock diagnosis's SAM outlines and example measurements, plus the default
// clearance. backend/export_how_it_works.py builds it through verify.py and writes public/hiw/*.stl and hiw.json.
const { t: T, d: D, c: C } = HIW
const VERIFY = HIW.verify // static: verify.py's report on the old corner-chip piece
const ROWS: VerifyResult = { ok: true, error: null, clearance: C, checks: [ // shown as the inspector shows them in the app
  { name: 'Watertight, single body', ok: true, value: `${VERIFY.bodies} body`, expected: null },
  { name: 'Overall size', ok: true, value: VERIFY.bbox.map((x) => x.toFixed(1)).join(' × ') + ' mm', expected: VERIFY.expected_bbox.map((x) => x.toFixed(1)).join(' × ') + ' ± 0.3' },
  { name: 'Overlap with the table', ok: true, value: `${VERIFY.interference_volume.toFixed(3)} mm³`, expected: '0' },
  { name: 'Gap to the break', ok: true, value: `${VERIFY.gap.typical.toFixed(2)} mm typical`, expected: `${C.toFixed(2)} on ${VERIFY.gaps.length} faces` },
] }
const CODE = HIW.code // the passing Muse Spark Open answer at these values, wrapped to fit a phone
const LIFT = 28 // the piece is built this far above the chip, then slides down into it

const STEPS: { title: string; sheet: string; body: string; tags?: string[] }[] = [
  { title: 'Something broke.', sheet: 'Broken corner',
    body: 'A chunk knocked off the corner of a perfectly good table. Too small a reason to replace the table, too fiddly to model the missing piece in CAD yourself.' },
  { title: 'Snap three photos.', sheet: 'Capture', tags: ['Muse Spark'],
    body: 'A shot list walks you through a top view, a side view and a close-up of the damage. A live level keeps each shot square, and Muse Spark checks every photo before you move on.' },
  { title: 'SAM 3.1 outlines what’s missing.', sheet: 'Segmentation', tags: ['SAM 3.1', 'Muse Spark'],
    body: 'SAM 3.1 outlines the missing area in the top view and in the side view. Muse Spark reads all three shots, picks the fix (here, the missing piece itself) and works out what to measure.' },
  { title: 'Measure two things.', sheet: 'Measurements',
    body: 'The app marks exactly where to put the ruler. The tabletop thickness is the one reference that scales both outlines to millimetres, and the chip depth sets how deep the piece goes. Clearance comes pre-filled.' },
  { title: 'Muse Spark Open builds the missing piece.', sheet: 'CAD generation', tags: ['Muse Spark Open'],
    body: 'The outlines go to Muse Spark Open, which writes CadQuery like this: extrude the top outline down and the side outline across, keep where they overlap, then shrink it 0.2 mm so it slides in, flattening break features under 1 mm.' },
  { title: 'Checked against the break.', sheet: 'Inspection',
    body: 'Every attempt is built and inspected against the damaged corner: one watertight body, no overlap with the wood, a gap close to 0.2 mm all round, and at least 90% of the missing volume filled. If a check fails, the inspector’s notes go back to the model, up to three attempts.' },
  { title: 'The corner is whole again.', sheet: 'Ready to print',
    body: 'Download the STL, print it top face down and glue it into the chip with epoxy. It sits flush with the tabletop and both edges.' },
]

// ---- timeline: everything is a function of s, the scroll position in steps (step k spans k..k+1) ----

const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
/** 0 before a, 1 after b, eased in between. */
const ramp = (a: number, b: number, x: number) => { const u = clamp01((x - a) / (b - a)); return u * u * (3 - 2 * u) }
/** Fades in over a→b and out over c→d. */
const win = (a: number, b: number, c: number, d: number, x: number) => ramp(a, b, x) * (1 - ramp(c, d, x))
const pad = (n: number) => String(n).padStart(2, '0')

// s, azimuth°, elevation°, distance, target xyz. CadQuery frame: Z up, table corner at the origin, table at x, y >= 0.
const OPENING = [235, 26, 165, 14, 14, 4]
const CAM = [
  [0.00, ...OPENING],
  [0.80, ...OPENING],
  [1.06, 360, 88, 150, 20, 20, 9], // shot 1: top, corner top-left like the app's guide frame
  [1.22, 360, 88, 150, 20, 20, 9],
  [1.34, 270, 3, 140, 26, 0, 9], // shot 2: side, level with the tabletop
  [1.46, 270, 3, 140, 26, 0, 9],
  [1.58, 225, 34, 100, 11, 9, 13], // shot 3: close-up of the chip
  [1.74, 225, 34, 100, 11, 9, 13],
  [2.10, 240, 32, 125, 13, 9, 12], // segmentation: both outlines in view
  [2.95, 240, 32, 125, 13, 9, 12],
  [3.12, 248, 20, 175, 25, 8, 7], // measurements: the front face
  [3.95, 248, 20, 175, 25, 8, 7],
  [4.12, 235, 20, 170, 12, 10, 26], // CAD: built above the chip
  [5.02, 235, 20, 170, 12, 10, 26],
  [5.32, 235, 32, 115, 12, 10, 13], // slides down into it
  [5.46, 235, 32, 115, 12, 10, 13], // inspection
  [6.00, 235, 32, 115, 12, 10, 13],
  [6.25, ...OPENING], // the opening shot, whole again
]
function cam(s: number) {
  let i = 0
  while (i < CAM.length - 2 && s > CAM[i + 1][0]) i++
  const a = CAM[i], b = CAM[i + 1], u = ramp(a[0], b[0], s)
  return a.map((v, k) => v + (b[k] - v) * u)
}

const TYPE = [4.1, 4.62] // the code types out over this range of s
const SHOTS: [number, number, V3, V3, string][] = [ // hold from, hold to, region framed, label
  [1.06, 1.22, [0, 0, 0], [44, 44, T], 'TOP VIEW · LEVEL ✓'],
  [1.34, 1.46, [0, 0, 0], [60, 0, T], 'SIDE VIEW · LEVEL ✓'],
  [1.58, 1.74, [-1, -1, T - D - 1], [27, 22, T], 'CLOSE-UP'],
]
const OUTLINE_TAGS: [number, V3, Pt, string][] = [ // shows from, a point inside the outline, leader, label
  [2.12, [17, 5, T], [46, -48], 'TOP OUTLINE · SAM 3.1'],
  [2.34, [9, 0, T - 2.5], [-30, 54], 'SIDE OUTLINE · SAM 3.1'],
]
const DIMS: [V3, V3, V3, number][] = [ // from, to, offset direction, value: the two numbers the app asks for
  [[50, 0, 0], [50, 0, T], [0, -1, 0], T],
  [[0, 0, T - D], [0, 0, T], [0, -1, 0], D],
]
const STILL = [0.5, 1.18, 2.6, 3.8, 4.9, 5.8, 6.6] // a resting moment in each step, for reduced motion

// ---- 3D scene ----

const INK = 0x191917, ACCENT = 0xff5b14, DEG = Math.PI / 180
const loadGeos = (): Promise<Geos> =>
  Promise.all(PARTS.map((n) => new STLLoader().loadAsync(`/hiw/${n}.stl`)))
    .then((g) => Object.fromEntries(PARTS.map((n, i) => [n, g[i]])) as Geos)

function makeScene(geo: Geos) {
  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b09c, 2.2))
  const sun = new THREE.DirectionalLight(0xffffff, 1.5)
  sun.position.set(-70, 160, 100)
  scene.add(sun)
  const camera = new THREE.PerspectiveCamera(30, 1, 1, 3000)
  const root = new THREE.Group()
  root.rotation.x = -Math.PI / 2 // CadQuery is Z-up; three.js is Y-up
  scene.add(root)
  const outline = (g: THREE.BufferGeometry, color = INK) =>
    new THREE.LineSegments(new THREE.EdgesGeometry(g, 25), new THREE.LineBasicMaterial({ color, transparent: true }))

  const table = new THREE.Mesh(geo.table, new THREE.MeshStandardMaterial({ color: 0xe9e2d2, roughness: 1 }))
  table.add(outline(geo.table))

  // SAM 3.1's outlines where they were seen, the top one on the tabletop and the side one on the front face,
  // hatched in screen space like the outlines on the measure screen.
  const hatch = new THREE.ShaderMaterial({
    uniforms: { opacity: { value: 0 }, dpr: { value: 1 } },
    transparent: true, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    vertexShader: 'void main() { gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `uniform float opacity; uniform float dpr;
      void main() {
        float on = step(mod((gl_FragCoord.x + gl_FragCoord.y) / dpr, 6.0), 2.0);
        gl_FragColor = vec4(1.0, 0.357, 0.078, opacity * mix(0.35, 1.0, on));
      }`,
  })
  const flat = (pts: number[][]) => {
    const mat = hatch.clone()
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y)))), mat)
    const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts.map(([x, y]) => new THREE.Vector3(x, y, 0))),
      new THREE.LineBasicMaterial({ color: ACCENT, transparent: true }))
    mesh.add(line)
    return { mesh, mat, line }
  }
  const topOutline = flat(HIW.top), sideOutline = flat(HIW.side)
  topOutline.mesh.position.z = T + 0.05
  sideOutline.mesh.rotation.x = Math.PI / 2 // its (x, z) points onto the y = 0 face
  sideOutline.mesh.position.y = -0.05

  // The two prisms the code extrudes, each growing from its workplane, and the piece they intersect into.
  const prism = (g: THREE.BufferGeometry, axis: 'y' | 'z') => {
    g.computeBoundingBox()
    const base = g.boundingBox!.min[axis]
    g.translate(0, axis === 'y' ? -base : 0, axis === 'z' ? -base : 0)
    const mat = new THREE.MeshStandardMaterial({ color: ACCENT, roughness: 0.6, transparent: true, depthWrite: false })
    const mesh = new THREE.Mesh(g, mat), line = outline(g)
    mesh.position[axis] = base
    mesh.add(line)
    return { mesh, mat, line }
  }
  const prismA = prism(geo.prism_top, 'z'), prismB = prism(geo.prism_side, 'y')
  const pieceMat = new THREE.MeshStandardMaterial({ color: ACCENT, roughness: 0.6, transparent: true })
  const piece = new THREE.Mesh(geo.piece, pieceMat), pieceLine = outline(geo.piece)
  piece.add(pieceLine)
  const build = new THREE.Group()
  build.add(prismA.mesh, prismB.mesh, piece)
  root.add(table, topOutline.mesh, sideOutline.mesh, build)

  const v = new THREE.Vector3()
  return {
    scene, camera,
    setDpr(dpr: number) { topOutline.mat.uniforms.dpr.value = sideOutline.mat.uniforms.dpr.value = dpr },
    project(p: V3, w: number, h: number): Pt {
      v.set(p[0], p[2], -p[1]).project(camera)
      return [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * h]
    },
    /** Poses everything for scroll position s. Returns how many characters of CODE are typed. */
    set(s: number, time: number) {
      const [, az, el, dist, tx, ty, tz] = cam(s)
      const sway = (10 * (1 - ramp(0.5, 0.95, s)) + 8 * ramp(6.1, 6.5, s)) * Math.sin(time * 0.5)
      const a = (az + sway) * DEG, e = el * DEG
      camera.position.set(tx + dist * Math.cos(e) * Math.cos(a), tz + dist * Math.sin(e), -(ty + dist * Math.cos(e) * Math.sin(a)))
      camera.lookAt(tx, tz, -ty)
      camera.updateMatrixWorld()

      const typed = clamp01((s - TYPE[0]) / (TYPE[1] - TYPE[0])) * CODE.length
      const part = (from: string, to: string) => clamp01((typed - CODE.indexOf(from)) / (CODE.indexOf(to) - CODE.indexOf(from)))
      const pa = part('a = (', 'b = ('), pb = part('b = (', 'table ='), cut = ramp(TYPE[1] - 0.04, TYPE[1] + 0.1, s)

      // The outlines show in step 3 (top, then side), and again while their numbers type, until their prism grows.
      const seen = (from: number) => ramp(from, from + 0.18, s) * (1 - 0.4 * ramp(2.95, 3.1, s)) * (1 - ramp(3.96, 4.08, s))
      const typing = (p: number, grown: number) => ramp(0, 0.15, p) * (1 - ramp(0, 0.4, grown))
      const shown = [Math.max(seen(2.08), typing(part('top = [', 'side = ['), pa)), Math.max(seen(2.3), typing(part('side = [', '# push'), pb))]
      ;[topOutline, sideOutline].forEach((o, i) => {
        o.mesh.visible = shown[i] > 0.005
        o.mat.uniforms.opacity.value = o.line.material.opacity = shown[i]
      })

      ;[prismA, prismB].forEach((p, i) => {
        const u = i ? pb : pa, on = Math.min(1, u * 4) * (1 - cut)
        p.mesh.visible = on > 0.005
        p.mat.opacity = 0.3 * on
        p.line.material.opacity = on
        p.mesh.scale[i ? 'y' : 'z'] = Math.max(1e-3, u) // extrudes as its line types
      })
      piece.visible = cut > 0
      pieceMat.opacity = pieceLine.material.opacity = cut
      build.position.z = LIFT * (1 - ramp(5.02, 5.32, s))
      return typed
    },
  }
}

// ---- 2D overlay: brackets, dimensions and callouts, projected from 3D, as an SVG string ----

const f = (n: number) => n.toFixed(1)
const boxCorners = (lo: V3, hi: V3) =>
  [0, 1, 2, 3, 4, 5, 6, 7].map((i): V3 => [i & 1 ? hi[0] : lo[0], i & 2 ? hi[1] : lo[1], i & 4 ? hi[2] : lo[2]])

function overlay(s: number, proj: (p: V3) => Pt, w: number, h: number) {
  /** Ink label, mono 11px (6.6px a character), kept inside the frame; x is its left edge, centre or right edge. */
  const tag = (x: number, y: number, text: string, num = '', align: 'left' | 'center' | 'right' = 'center') => {
    const tw = 6.6 * (text.length + (num ? num.length + 1 : 0)) + 14
    const x0 = Math.min(Math.max(x - tw * { left: 0, center: 0.5, right: 1 }[align], 6), w - tw - 6), y0 = Math.min(Math.max(y - 10, 6), h - 26)
    return `<g class="tag" transform="translate(${f(x0)},${f(y0)})"><rect width="${f(tw)}" height="20" rx="2"/>`
      + `<text x="7" y="14">${num ? `<tspan class="n">${num}</tspan> ` : ''}${text}</text></g>`
  }
  const g = (op: number, body: string) => (op > 0.01 ? `<g opacity="${op.toFixed(2)}">${body}</g>` : '')
  const line = (cls: string, a: Pt, b: Pt, extra = '') =>
    `<line class="${cls}" x1="${f(a[0])}" y1="${f(a[1])}" x2="${f(b[0])}" y2="${f(b[1])}"${extra}/>`
  const dot = (p: Pt) => `<circle class="dot" cx="${f(p[0])}" cy="${f(p[1])}" r="3"/>`
  let out = ''

  // 02: viewfinder brackets lock onto each shot; the shot strip fills as photos are taken
  SHOTS.forEach(([a, b, lo, hi, name], j) => {
    const op = win(a - 0.06, a + 0.01, b - 0.01, b + 0.06, s)
    if (op < 0.01) return
    const pts = boxCorners(lo, hi).map(proj), xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1])
    const m = 12 + 28 * (1 - ramp(a - 0.06, a + 0.02, s)), L = 16
    const x0 = Math.max(8, Math.min(...xs) - m), x1 = Math.min(w - 8, Math.max(...xs) + m)
    const y0 = Math.max(36, Math.min(...ys) - m), y1 = Math.min(h - 8, Math.max(...ys) + m)
    out += g(op, `<path class="br" d="M${f(x0)} ${f(y0 + L)}V${f(y0)}H${f(x0 + L)}M${f(x1 - L)} ${f(y0)}H${f(x1)}V${f(y0 + L)}`
      + `M${f(x1)} ${f(y1 - L)}V${f(y1)}H${f(x1 - L)}M${f(x0 + L)} ${f(y1)}H${f(x0)}V${f(y1 - L)}"/>`
      + tag(x0, y0 - 16, `SHOT ${j + 1}/3 · ${name}`, '', 'left'))
  })
  out += g(win(0.97, 1.04, 1.8, 1.9, s), SHOTS.map(([a], j) => {
    const x = 14 + j * 32, cls = s > a + 0.08 ? 'th done' : s > a - 0.12 ? 'th now' : 'th'
    return `<rect class="${cls}" x="${x}" y="${h - 40}" width="26" height="26" rx="2"/><text class="thn" x="${x + 13}" y="${h - 23}">${j + 1}</text>`
  }).join(''))

  // 03: the outlines themselves are drawn in 3D; label them
  OUTLINE_TAGS.forEach(([a, at, [dx, dy], text]) => {
    const op = win(a, a + 0.12, 2.92, 3.02, s)
    if (op < 0.01) return
    const p = proj(at), q: Pt = [p[0] + dx, p[1] + dy]
    out += g(op, line('ld', p, q) + dot(p) + tag(q[0], q[1], text))
  })

  // 04: dimension lines grow out from their middle, then the reading appears
  DIMS.forEach(([a, b, d, value], i) => {
    const p = ramp(3.1 + 0.13 * i, 3.4 + 0.13 * i, s) * (1 - ramp(3.96, 4.06, s))
    if (p < 0.01) return
    const at = (q: V3, k: number) => proj([q[0] + d[0] * k, q[1] + d[1] * k, q[2] + d[2] * k])
    const A = at(a, 10), B = at(b, 10), M: Pt = [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2], u = ramp(0.15, 0.8, p)
    const grow = (P: Pt): Pt => [M[0] + (P[0] - M[0]) * u, M[1] + (P[1] - M[1]) * u]
    // A line too short to carry its label gets the label beside it, on the outward side (as on the measure screen).
    const text = `${value.toFixed(1)} mm`, tw = 6.6 * (text.length + 2) + 14, side = Math.sign(at(a, 30)[0] - A[0]) || 1
    const lx = Math.hypot(B[0] - A[0], B[1] - A[1]) < tw + 16 ? M[0] + side * (tw / 2 + 8) : M[0]
    out += g(Math.min(1, p * 3), line('ext', at(a, 2), at(a, 13)) + line('ext', at(b, 2), at(b, 13))
      + (u > 0.1 ? line('dl', grow(A), grow(B), ' marker-start="url(#hiw-a)" marker-end="url(#hiw-a)"') : '')
      + g(ramp(0.75, 1, p), tag(lx, M[1], text, String(i + 1))))
  })

  // 06: the gap verify.py measured at three seams, then fill ratio, overlap and the inspector's stamp
  const fit = 1 - ramp(5.96, 6.06, s), mid = proj([12, 10, 14])
  HIW.callouts.forEach(({ at, gap }, i) => {
    const op = ramp(5.36 + 0.05 * i, 5.43 + 0.05 * i, s) * fit
    if (op < 0.01) return
    const p = proj(at as V3), dx = p[0] - mid[0], dy = p[1] - mid[1], len = Math.hypot(dx, dy) || 1
    const q: Pt = [p[0] + (dx / len) * 54, Math.max(p[1] + (dy / len) * 54, 106)] // below the stack of checks, top left
    out += g(op, line('ld', p, q) + dot(p) + tag(q[0], q[1], `GAP ${gap.toFixed(2)} mm`, '✓', dx < 0 ? 'right' : 'left'))
  })
  out += g(ramp(5.56, 5.64, s) * fit, tag(14, 22, `FILL ${(VERIFY.fill_ratio * 100).toFixed(1)}%`, '✓', 'left')
    + tag(14, 48, `OVERLAP ${VERIFY.interference_volume.toFixed(3)} mm³`, '✓', 'left')
    + tag(14, 74, `WATERTIGHT · ${VERIFY.bodies} BODY`, '✓', 'left'))
  const st = ramp(5.62, 5.72, s) * fit
  out += g(st, `<g transform="translate(${f(w - 54)},34) rotate(-4) scale(${(1 + 0.7 * (1 - st)).toFixed(2)})">`
    + `<rect class="stamp" x="-34" y="-14" width="68" height="28" rx="3"/><text class="stamp-t" y="5">PASS</text></g>`)
  return out
}

// ---- page ----

function Card({ k, onStart, codeRef, still }: { k: number; onStart: () => void; codeRef?: Ref<HTMLElement>; still?: boolean }) {
  const { title, body, tags } = STEPS[k]
  const Title = k === 0 ? 'h1' : 'h2'
  return (
    <div className="hiw-card">
      <p className="eyebrow">How it works · <span className="accent">{pad(k + 1)}</span> / 07</p>
      <Title>{title}</Title>
      <p className="body">{body}</p>
      {k === 4 && <pre className="hiw-code"><code ref={codeRef} className={still ? 'still' : undefined}>{still ? CODE : ''}</code></pre>}
      {k === 5 && <Checks v={ROWS} />}
      {tags && <div className="byline">{tags.map((t) => <ModelTag key={t}>{t}</ModelTag>)}</div>}
      {k === 6 && <button className="btn btn-primary" onClick={onStart}>Fix something <span className="arrow">→</span></button>}
    </div>
  )
}

/** A pinned 3D stage beside (desktop) or above (phone) the step cards; scrolling drives the timeline. */
function Scrolly({ onStart }: { onStart: () => void }) {
  const root = useRef<HTMLDivElement>(null), stage = useRef<HTMLDivElement>(null), view = useRef<HTMLDivElement>(null)
  const ov = useRef<SVGGElement>(null), steps = useRef<HTMLDivElement>(null), code = useRef<HTMLElement>(null)
  const sheetName = useRef<HTMLElement>(null), sheetNo = useRef<HTMLElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')

  useEffect(() => {
    root.current!.style.setProperty('--bar', `${document.querySelector('.topbar')?.getBoundingClientRect().height ?? 47}px`)
    let renderer: THREE.WebGLRenderer
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }) } catch { setStatus('failed'); return }
    renderer.setPixelRatio(Math.min(devicePixelRatio, matchMedia('(pointer: coarse)').matches ? 1.5 : 2))
    view.current!.prepend(renderer.domElement)
    const desktop = matchMedia('(min-width: 900px)')
    let raf = 0, alive = true, ro: ResizeObserver | undefined

    /** Which step the reading line is in, plus how far through it: the stage's middle on desktop; on a phone, where the cards pin. */
    const progress = () => {
      const r = stage.current!.getBoundingClientRect(), y = desktop.matches ? (r.top + r.bottom) / 2 : r.bottom + 16
      const secs = steps.current!.children
      for (let i = 0; i < secs.length; i++) {
        const b = secs[i].getBoundingClientRect()
        if (y < b.bottom || i === secs.length - 1) return Math.min(Math.max(i + (y - b.top) / b.height, 0), secs.length - 0.001)
      }
      return 0
    }

    loadGeos().then((geo) => {
      if (!alive) return
      const sc = makeScene(geo)
      sc.setDpr(renderer.getPixelRatio())
      setStatus('ready')
      let w = 0, h = 0, sd = -1, last = performance.now(), drawn = '', svg = '', typed = -1, step = -1
      ro = new ResizeObserver(() => {
        w = view.current!.clientWidth
        h = view.current!.clientHeight
        renderer.setSize(w, h)
        sc.camera.aspect = w / h
        sc.camera.updateProjectionMatrix()
        drawn = ''
      })
      ro.observe(view.current!)
      const frame = (now: number) => {
        raf = requestAnimationFrame(frame)
        const s = progress(), dt = Math.min(0.1, (now - last) / 1000)
        last = now
        sd = sd < 0 ? s : sd + (s - sd) * (1 - Math.exp(-dt * 7)) // ease toward the scroll position: smooth under touch scrolling
        const key = sd.toFixed(4) + (sd < 0.95 || sd > 6.1 ? now : '') // steps 1 and 7 sway, so they redraw every frame
        if (key === drawn || !w) return
        drawn = key
        const n = Math.round(sc.set(sd, now / 1000))
        renderer.render(sc.scene, sc.camera)
        const next = overlay(sd, (p) => sc.project(p, w, h), w, h)
        if (next !== svg) ov.current!.innerHTML = svg = next
        if (n !== typed) {
          code.current!.textContent = CODE.slice(0, (typed = n))
          code.current!.parentElement!.scrollTop = 1e4 // phone: the short code window follows the newest line
        }
        if (Math.floor(sd) !== step) {
          step = Math.floor(sd)
          sheetName.current!.textContent = STEPS[step].sheet
          sheetNo.current!.textContent = `${pad(step + 1)} / 07`
        }
      }
      raf = requestAnimationFrame(frame)
    }).catch(() => alive && setStatus('failed'))

    return () => {
      alive = false
      cancelAnimationFrame(raf)
      ro?.disconnect()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [])

  return (
    <div className="hiw" ref={root}>
      <div className="hiw-stage" ref={stage} aria-hidden="true">
        <div className="hiw-view" ref={view}>
          <svg className="hiw-ov"><g ref={ov} /></svg>
          {status !== 'ready' && <span className="hiw-msg">{status === 'loading' ? 'Loading model…' : '3D view unavailable'}</span>}
        </div>
        <div className="titleblock">
          <div><span>Stage</span><b ref={sheetName}>{STEPS[0].sheet}</b></div>
          <div><span>Sheet</span><b ref={sheetNo}>01 / 07</b></div>
          <div><span>Part</span><b>Missing piece</b></div>
        </div>
      </div>
      <div className="hiw-steps" ref={steps}>
        {STEPS.map((_, k) => <section className="hiw-step" key={k}><Card k={k} onStart={onStart} codeRef={code} /></section>)}
      </div>
    </div>
  )
}

/** prefers-reduced-motion: the same scenes as still frames, one per step, and nothing moves. */
function Still({ onStart }: { onStart: () => void }) {
  const [frames, setFrames] = useState<{ img: string; svg: string }[]>([])
  useEffect(() => {
    let alive = true
    loadGeos().then((geo) => {
      if (!alive) return
      const w = 640, h = 480, renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
      renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
      renderer.setSize(w, h, false)
      const sc = makeScene(geo)
      sc.camera.aspect = w / h
      sc.camera.updateProjectionMatrix()
      sc.setDpr(renderer.getPixelRatio())
      setFrames(STILL.map((s) => {
        sc.set(s, 0)
        renderer.render(sc.scene, sc.camera)
        return { img: renderer.domElement.toDataURL(), svg: overlay(s, (p) => sc.project(p, w, h), w, h) }
      }))
      renderer.dispose()
      renderer.forceContextLoss()
    }).catch(() => {}) // no WebGL: the cards still read fine on their own
    return () => { alive = false }
  }, [])
  return (
    <div className="hiw-still">
      {STEPS.map((_, k) => (
        <section className="hiw-step" key={k}>
          <figure className="hiw-fig" aria-hidden="true">
            {frames[k] && <><img src={frames[k].img} alt="" /><svg className="hiw-ov" viewBox="0 0 640 480" dangerouslySetInnerHTML={{ __html: frames[k].svg }} /></>}
          </figure>
          <Card k={k} onStart={onStart} still />
        </section>
      ))}
    </div>
  )
}

export default function HowItWorks({ onStart }: { onStart: () => void }) {
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches
  return (
    <>
      <svg className="hiw-defs" aria-hidden="true"><defs><ArrowDefs id="hiw-a" color="var(--accent)" /></defs></svg>
      {still ? <Still onStart={onStart} /> : <Scrolly onStart={onStart} />}
    </>
  )
}
