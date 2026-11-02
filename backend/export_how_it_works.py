"""Export the How-it-works page's assets. Re-run after changing fixes/chip_fill.py or mocks/diagnose.json.

frontend/public/hiw/
  piece.stl       the real chip_fill piece at the app's mock-mode defaults, built and checked by verify.py
  table.stl       the damaged table it fits (chip_fill.mating_solid), as verify.py exported it
  prism_top.stl   the top outline extruded vertically, exactly as the code builds it
  prism_side.stl  the side outline extruded horizontally
frontend/src/hiw.json
  the measurements, SAM's outlines in mm, the piece's flush faces (front and top, for the landing drawing),
  verify.py's report, gap callouts on the visible seams, and the passing Muse Spark Open code
  (mocks/spark_cad_chip_fill.json) at these values, wrapped to fit a phone
"""
import inspect
import json
import math
import shutil
from pathlib import Path

import cadquery as cq
from OCP.BRepTools import BRepTools_WireExplorer
from OCP.TopAbs import TopAbs_REVERSED

from fixes import chip_fill
from verify import _on_face, verify

P = chip_fill.example()
T, D, C = P["edge_thickness"], P["chip_depth"], P["clearance"]
ROOT = Path(__file__).parent.parent
OUT = ROOT / "frontend" / "public" / "hiw"

res = verify(inspect.getsource(chip_fill) + f"\nresult = make(**{P!r})\n", "chip_fill", P)
assert res["ok"], res["error"]
assert res["interference_volume"] == 0 and res["gap"]["typical"] == C and res["fill_ratio"] >= 0.9, res
OUT.mkdir(parents=True, exist_ok=True)
for old in ("cap.stl", "damage.stl"):
    (OUT / old).unlink(missing_ok=True)
shutil.copy(res["stl_path"], OUT / "piece.stl")
shutil.copy(res["mate_path"], OUT / "table.stl")
for name, wp in zip(("prism_top", "prism_side"), chip_fill.prisms(**P)):
    cq.exporters.export(wp, str(OUT / f"{name}.stl"), tolerance=0.05, angularTolerance=0.2)

# Gap callouts: each break face's measured gap, pinned to its seam you can see once the piece is in
# (its edge on the tabletop, z = t, or on the front face, y = 0). Two on top and one in front: the largest faces
# whose seams are at least 10 mm from the callouts already chosen, so they spread around the break.
piece, seams = chip_fill.make(**P).val(), {"top": [], "front": []}
for f in chip_fill.mating_solid(**P).val().Faces():
    p = _on_face(f)
    hit = piece.intersect(cq.Edge.makeLine(p, p + f.normalAt(p) * 1000))
    for e in f.Edges() if hit.Edges() else []:
        ends = (e.startPoint(), e.endPoint(), e.Center())  # OCCT's edge bounding boxes aren't tight
        where = "top" if all(abs(v.z - T) < 1e-4 for v in ends) else "front" if all(abs(v.y) < 1e-4 for v in ends) else None
        if where and e.Length() > 2:
            gap = cq.Vertex.makeVertex(*p.toTuple()).distance(hit)
            seams[where].append((f.Area(), [round(v, 2) for v in e.Center().toTuple()], round(gap, 2)))
callouts = []
for k in ("top", "top", "front"):
    _, at, g = next(c for c in sorted(seams[k], reverse=True) if all(math.dist(c[1], o["at"]) >= 10 for o in callouts))
    callouts.append({"at": at, "gap": g})
assert len(callouts) == 3, seams


def face_outline(face, axes):
    """A flat face's outer wire in traversal order, as [a, b] mm on the given axes; arcs sampled every 0.4 mm."""
    out, ex = [], BRepTools_WireExplorer(face.outerWire().wrapped)
    while ex.More():
        e = cq.Edge(ex.Current())
        n = 1 if e.geomType() == "LINE" else max(2, round(e.Length() / 0.4))
        ts = [i / n for i in range(n)]
        out += [e.positionAt(1 - u if ex.Orientation() == TopAbs_REVERSED else u).toTuple() for u in ts]
        ex.Next()
    return [[round(p[i], 2) for i in axes] for p in out]


# The piece's faces that sit flush with the table: the front (y = 0, as [x, z]) and the top (z = t, as [x, y]).
front = [f for f in piece.Faces() if abs(f.Center().y) < 1e-6]
top_face = [f for f in piece.Faces() if abs(f.Center().z - T) < 1e-6]
assert len(front) == len(top_face) == 1, (len(front), len(top_face))
piece_front, piece_top = face_outline(front[0], (0, 2)), face_outline(top_face[0], (0, 1))


def pts(name, xs, per=3):
    rows = [", ".join(f"({x:g}, {y:g})" for x, y in xs[i:i + per]) for i in range(0, len(xs), per)]
    return f"{name} = [" + ",\n  ".join(rows) + "]"


xmax, ymax = max(x for x, _ in P["top"]), max(y for _, y in P["top"])
code = f"""import cadquery as cq

t, d, c, r, E = {T:g}, {D:g}, {C:g}, 0.5, 5
{pts("top", P["top"])}
{pts("side", P["side"])}
# push the face points past the table faces
top = [(-E, -E), (top[1][0], -E),
  *top[1:], (-E, top[-1][1])]
side = [(-E, t+E), (side[1][0], t+E),
  *side[1:], (-E, side[-1][1])]

a = (cq.Workplane("XY", origin=(0, 0, t-d-E))
  .polyline(top).close()
  .offset2D(-c-r).offset2D(r)
  .extrude(d + 2*E))
b = (cq.Workplane("XZ", origin=(0, -E, 0))
  .polyline(side).close()
  .offset2D(-c-r).offset2D(r)
  .extrude(-({ymax:g} + 2*E)))
table = cq.Workplane().box(
  {xmax:g}+E, {ymax:g}+E, t, centered=False)
result = a.intersect(b).intersect(table)"""
assert max(map(len, code.splitlines())) <= 48, "keep lines phone-width"

keep = ("ok", "error", "watertight", "bodies", "bbox", "expected_bbox", "interference_volume", "gaps", "gap", "fill_ratio")
data = {"t": T, "d": D, "c": C, "top": P["top"], "side": P["side"], "piece_front": piece_front, "piece_top": piece_top,
        "callouts": callouts, "code": code,
        "verify": {k: res[k] for k in keep}}
(ROOT / "frontend" / "src" / "hiw.json").write_text(json.dumps(data, indent=1) + "\n")
print(json.dumps({k: res[k] for k in ("bbox", "gap", "fill_ratio", "interference_volume", "watertight", "bodies")}))
print("callouts", callouts)
print(f"piece + table + 2 prisms -> {OUT}; data -> frontend/src/hiw.json")
