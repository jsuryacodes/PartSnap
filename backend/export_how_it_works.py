"""Export the How-it-works page's 3D assets to frontend/public/hiw/. Re-run after changing fixes/corner_cap.py.

cap.stl     the real corner cap at the app's default measurements, built and checked by verify.py
table.stl   a tabletop corner with a chip, in the same frame (corner vertex at the origin)
damage.stl  only the chip's broken faces, for the segmentation highlight
"""
import inspect
import json
import shutil
from pathlib import Path

import cadquery as cq

from fixes import corner_cap
from verify import verify

# The app's defaults: the diagnosis examples (18 / 40 / 40) plus make()'s wall and clearance.
P = dict(edge_thickness=18, reach_x=40, reach_y=40, wall=2.0, clearance=0.2)
OUT = Path(__file__).parent.parent / "frontend" / "public" / "hiw"
L = 110  # length of the table sample along each edge (mm)

res = verify(inspect.getsource(corner_cap) + f"\nresult = make(**{P!r})\n", "corner_cap", P)
assert res["ok"], res["error"]
assert res["gaps"] == {"-x": 0.2, "-y": 0.2, "-z": 0.2, "+z": 0.2} and res["interference_volume"] == 0, res
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy(res["stl_path"], OUT / "cap.stl")

# A chip about 1 cm across at the top corner: a tapered chunk, 6 mm deep, lofted down from above the top face.
t = P["edge_thickness"]
top = [(-4, -4), (13, -4), (9.5, 3), (6.5, 4.5), (5.5, 7), (3, 8.5), (-4, 11.5)]
bottom = [(-4, -4), (4, -4), (3, 1), (2, 1.5), (1.6, 2.4), (1, 2.8), (-4, 4)]
chip = (cq.Workplane().workplane(offset=t - 6).polyline(bottom).close()
        .workplane(offset=7).polyline(top).close().loft(ruled=True))
table = cq.Workplane().box(L, L, t, centered=False).cut(chip).val()


def on_block(f):
    """True for faces left over from the original block (x, y in {0, L}; z in {0, t}), i.e. not the break."""
    b = f.BoundingBox()
    return any(hi - lo < 1e-6 and min(abs(lo), abs(lo - end)) < 1e-6
               for lo, hi, end in ((b.xmin, b.xmax, L), (b.ymin, b.ymax, L), (b.zmin, b.zmax, t)))


damage = [f for f in table.Faces() if not on_block(f)]
assert 4 <= len(damage) <= 12, len(damage)
cq.exporters.export(table, str(OUT / "table.stl"), tolerance=0.05, angularTolerance=0.2)
cq.exporters.export(cq.Compound.makeCompound(damage), str(OUT / "damage.stl"), tolerance=0.05, angularTolerance=0.2)
print(json.dumps({k: res[k] for k in ("bbox", "gaps", "interference_volume", "watertight", "bodies")}))
print(f"cap + table + {len(damage)} damage faces -> {OUT}")
