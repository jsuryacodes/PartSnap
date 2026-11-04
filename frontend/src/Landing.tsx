import { c as C, d as D, piece_front, piece_top, side, t as T, verify } from './hiw.json'
import { ArrowDefs, ModelTag } from './ui'

/** Shop drawing of the real default fix (backend/export_how_it_works.py): the front view, with the piece lifted out
 *  of its chip, and the top view, where it sits in the chip because lifting doesn't change the plan. Millimetres. */
function HeroDrawing() {
  const ink = 'var(--ink)', k = 7.56, X0 = 62, Y0 = 266, W = 46, LIFT = 12 // 7.56 px/mm is 2:1 at 480 px wide
  const fp = ([x, z]: number[]) => `${(X0 + x * k).toFixed(1)},${(Y0 - z * k).toFixed(1)}` // front view: x right, z up
  const ks = 3.2, PX = 284, PY = 112 // top view: x right, y up (front edge at the bottom), as drawn in third angle
  const tp = ([x, y]: number[]) => `${(PX + x * ks).toFixed(1)},${(PY - y * ks).toFixed(1)}`
  const zig = (along: (u: number, off: number) => number[], n = 4) => // a break line, where the drawing stops
    Array.from({ length: n + 1 }, (_, i) => along(i / n, i % 2 ? (i % 4 === 1 ? 0.8 : -0.8) : 0))
  const table = [[0, 0], ...zig((u, o) => [W + o, u * T]), ...side.slice(1)]
  const plan = [[0, 0], ...zig((u, o) => [W + o, u * 26]).slice(0, -1), [W, 26], ...zig((u, o) => [W * (1 - u), 26 + o]).slice(1)]
  return (
    <figure className="drawing" style={{ margin: 0 }}>
      <svg viewBox="0 0 480 312" role="img" aria-label={`Front and top views: the missing piece of a chipped tabletop corner, lifted out of the chip it fills, ${C} mm gap to the break`}>
        <defs>
          <ArrowDefs id="h-arrow" color={ink} />
          <pattern id="h-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="7" stroke="var(--muted)" strokeWidth="1" />
          </pattern>
        </defs>

        {/* front view: the tabletop edge with SAM's side outline as the chip, and the piece lifted out of it */}
        <polygon points={table.map(fp).join(' ')} fill="url(#h-hatch)" stroke={ink} strokeWidth="1.5" strokeLinejoin="round" />
        <polygon points={piece_front.map(([x, z]) => fp([x, z + LIFT])).join(' ')} fill="var(--accent)" stroke={ink} strokeWidth="1.5" strokeLinejoin="round" />
        <g stroke={ink} strokeWidth="1" strokeDasharray="4 3">
          <line x1={X0 + 6 * k} y1={Y0 - 20 * k} x2={X0 + 6 * k} y2={Y0 - 12.6 * k} markerEnd="url(#h-arrow)" />
          <line x1={X0 + 17 * k} y1={Y0 - 23.6 * k} x2={X0 + 17 * k} y2={Y0 - 15.4 * k} markerEnd="url(#h-arrow)" />
        </g>

        {/* the two numbers the app asks for */}
        <g stroke={ink} strokeWidth="0.9">
          <line x1={X0 + W * k + 8} y1={Y0} x2={X0 + W * k + 40} y2={Y0} />
          <line x1={X0 + W * k + 8} y1={Y0 - T * k} x2={X0 + W * k + 40} y2={Y0 - T * k} />
          <line x1={X0 + W * k + 32} y1={Y0} x2={X0 + W * k + 32} y2={Y0 - T * k} markerStart="url(#h-arrow)" markerEnd="url(#h-arrow)" />
          <line x1={X0 - 6} y1={Y0 - T * k} x2={X0 - 38} y2={Y0 - T * k} />
          <line x1={X0 - 6} y1={Y0 - (T - D) * k} x2={X0 - 38} y2={Y0 - (T - D) * k} />
          <line x1={X0 - 30} y1={Y0 - T * k} x2={X0 - 30} y2={Y0 - (T - D) * k} markerStart="url(#h-arrow)" markerEnd="url(#h-arrow)" />
        </g>
        <text className="dt" textAnchor="middle" transform={`translate(${X0 + W * k + 46} ${Y0 - (T * k) / 2}) rotate(-90)`}>{T.toFixed(1)}</text>
        <text className="dt" textAnchor="middle" transform={`translate(${X0 - 36} ${Y0 - (T - D / 2) * k}) rotate(-90)`}>{D.toFixed(1)}</text>

        {/* callouts */}
        <g stroke={ink} strokeWidth="0.9" fill="none">
          <polyline points={`${fp([20.2, 13.9])} ${X0 + 26 * k},${Y0 - 9 * k} ${X0 + 34 * k},${Y0 - 9 * k}`} />
        </g>
        <circle cx={X0 + 20.2 * k} cy={Y0 - 13.9 * k} r="2.5" fill={ink} />
        <rect x={X0 + 34.3 * k} y={Y0 - 9 * k - 10} width="62" height="19" fill="var(--paper-hi)" />
        <text x={X0 + 34.6 * k} y={Y0 - 9 * k + 4} className="dt">GAP {C.toFixed(1)}</text>

        {/* top view */}
        <polygon points={plan.map(tp).join(' ')} fill="var(--paper-hi)" stroke={ink} strokeWidth="1.2" strokeLinejoin="round" />
        <polygon points={piece_top.map(tp).join(' ')} fill="var(--accent)" stroke={ink} strokeWidth="1.2" strokeLinejoin="round" />

        <text x={X0 + (W * k) / 2} y={Y0 + 30} textAnchor="middle" className="dt small">FRONT VIEW</text>
        <text x={PX + (W * ks) / 2} y={PY - 26 * ks - 10} textAnchor="middle" className="dt small">TOP VIEW</text>
        <style>{`.dt{font-family:var(--mono);font-size:13px;font-weight:500;fill:var(--ink)}.dt.small{font-size:10px;letter-spacing:.12em;fill:var(--muted)}`}</style>
      </svg>
      <div className="titleblock">
        <div><span>Part</span><b>Missing piece</b></div>
        <div><span>Gap</span><b>{C.toFixed(1)}</b></div>
        <div><span>Fill</span><b>{(verify.fill_ratio * 100).toFixed(1)}%</b></div>
      </div>
    </figure>
  )
}

const STEPS = [
  ['01', 'Snap', 'Three guided photos. SAM 3.1 outlines what’s missing, from the top and from the side.'],
  ['02', 'Measure', 'Two ruler readings: the tabletop thickness, which scales the outlines to millimetres, and the chip depth.'],
  ['03', 'Print', 'The CAD is written, then checked against the break before you download: no overlap, a 0.2\u00a0mm gap, 90%+ filled. Glue it in.'],
]

export default function Landing({ onStart }: { onStart: () => void }) {
  return (
    <div className="screen landing">
      <div className="hero">
        <div>
          <p className="eyebrow"><span className="accent">■</span> Repair, not replace</p>
          <h1 style={{ marginTop: 14 }}>Chipped? Snap&nbsp;it. <em>Print the missing piece.</em></h1>
          <p className="lede">Photograph the chip from the top and the side, take two ruler measurements, and download the exact missing piece as a 3D-printable STL, checked against the break before you print. Glue it in and the corner is whole again.</p>
          <div className="hero-cta">
            <button className="btn btn-primary" onClick={onStart}>Fix something <span className="arrow">→</span></button>
            <div className="byline" style={{ marginTop: 0 }}>
              Powered by Meta models
              <ModelTag>Muse Spark</ModelTag><ModelTag>SAM 3.1</ModelTag><ModelTag>Muse Wonder</ModelTag><ModelTag>Muse Spark Open</ModelTag>
            </div>
          </div>
        </div>
        <HeroDrawing />
      </div>
      <ol className="steps3">
        {STEPS.map(([n, t, d]) => (
          <li key={n}><span className="num">{n}</span><h3>{t}</h3><p>{d}</p></li>
        ))}
      </ol>
    </div>
  )
}
