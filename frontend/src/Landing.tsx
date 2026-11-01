import { ArrowDefs, ModelTag } from './ui'

/** Section view of the corner cap over a chipped tabletop, drawn like a shop drawing. */
function HeroDrawing() {
  const ink = 'var(--ink)'
  return (
    <figure className="drawing" style={{ margin: 0 }}>
      <svg viewBox="0 0 480 280" role="img" aria-label="Section drawing: a corner cap fitted over a chipped tabletop edge with 0.2 mm clearance">
        <defs>
          <ArrowDefs id="h-arrow" color={ink} />
          <pattern id="h-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="7" stroke="var(--muted)" strokeWidth="1" />
          </pattern>
        </defs>

        {/* tabletop, chipped at the corner, broken off on the right */}
        <path d="M396 120 L186 120 L179 127 L173 125 L170 136 L170 180 L396 180" fill="url(#h-hatch)" stroke={ink} strokeWidth="1.5" />
        <path d="M396 120 L390 136 L402 150 L390 164 L396 180" fill="none" stroke={ink} strokeWidth="1.2" />

        {/* the cap, in section */}
        <path d="M300 100 L150 100 L150 200 L300 200 L300 189 L161 189 L161 111 L300 111 Z" fill="var(--accent)" stroke={ink} strokeWidth="1.5" />

        {/* reach */}
        <g stroke={ink} strokeWidth="0.9">
          <line x1="150" y1="96" x2="150" y2="58" />
          <line x1="300" y1="96" x2="300" y2="58" />
          <line x1="150" y1="66" x2="300" y2="66" markerStart="url(#h-arrow)" markerEnd="url(#h-arrow)" />
        </g>
        <text x="225" y="58" textAnchor="middle" className="dt">40.0</text>

        {/* thickness */}
        <g stroke={ink} strokeWidth="0.9">
          <line x1="410" y1="120" x2="446" y2="120" />
          <line x1="410" y1="180" x2="446" y2="180" />
          <line x1="438" y1="120" x2="438" y2="180" markerStart="url(#h-arrow)" markerEnd="url(#h-arrow)" />
        </g>
        <text x="444" y="154" className="dt" textAnchor="start" transform="rotate(-90 444 154)" dx="-14" dy="12">18.0</text>

        {/* callouts */}
        <g stroke={ink} strokeWidth="0.9" fill="none">
          <polyline points="166,116 120,50 70,50" />
          <polyline points="150,170 110,232 70,232" />
        </g>
        <circle cx="166" cy="116" r="2.5" fill={ink} />
        <circle cx="150" cy="170" r="2.5" fill={ink} />
        <text x="70" y="44" className="dt">GAP 0.2</text>
        <text x="70" y="226" className="dt">WALL 2.0</text>

        <text x="240" y="262" textAnchor="middle" className="dt small">SECTION A–A · SCALE 2:1</text>
        <style>{`.dt{font-family:var(--mono);font-size:13px;font-weight:500;fill:var(--ink)}.dt.small{font-size:10px;letter-spacing:.12em;fill:var(--muted)}`}</style>
      </svg>
      <div className="titleblock">
        <div><span>Part</span><b>Corner cap</b></div>
        <div><span>Mat</span><b>PLA</b></div>
        <div><span>Tol</span><b>±0.1</b></div>
      </div>
    </figure>
  )
}

const STEPS = [
  ['01', 'Snap', 'Three guided photos. A live level keeps every shot square.'],
  ['02', 'Measure', 'The AI marks exactly where to put the ruler: 2–3 numbers, nothing more.'],
  ['03', 'Print', 'CAD is written, then checked for fit against your measurements before you download.'],
]

export default function Landing({ onStart }: { onStart: () => void }) {
  return (
    <div className="screen landing">
      <div className="hero">
        <div>
          <p className="eyebrow"><span className="accent">■</span> Repair, not replace</p>
          <h1 style={{ marginTop: 14 }}>Broken? Snap&nbsp;it. <em>Print the fix.</em></h1>
          <p className="lede">Photograph the damage, take a couple of ruler measurements, and download a 3D-printable part that fits, verified to a tenth of a millimetre.</p>
          <div className="hero-cta">
            <button className="btn btn-primary" onClick={onStart}>Fix something <span className="arrow">→</span></button>
            <div className="byline" style={{ marginTop: 0 }}>
              Powered by Meta models
              <ModelTag>Muse Spark</ModelTag><ModelTag>SAM 3.1</ModelTag><ModelTag>Muse Spark Open</ModelTag>
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
