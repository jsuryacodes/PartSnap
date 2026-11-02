"""Chip fill: the exact missing piece of a chipped tabletop corner, shaped from two photo outlines, glued into the chip.

Frame (mm): the table corner vertex is at the origin and the tabletop occupies x >= 0, y >= 0, 0 <= z <= edge_thickness.
`top` outlines the missing area seen from above, as [x, y] points; `side` outlines it seen from the front (the y = 0
face), as [x, z] points. Each outline starts at the corner, runs along one table face, follows the break line, and
ends on the other face: top goes (0, 0) -> (x1, 0) -> break -> (0, yn); side goes (0, t) -> (x1, t) -> break -> (0, zn).
Build the piece: push each outline's face points E = 5 mm past the table faces, so offsets move only the break line;
shrink by the clearance plus 0.5 mm and grow back 0.5 mm (2D offsets), which flattens break features under 1 mm;
extrude the top outline vertically and the side outline horizontally (along y) and intersect them; clip to the
table (x >= 0, y >= 0, z <= t) so the piece is flush with the top and both faces.
"""
import math

import cadquery as cq

PARAMS = {
    "edge_thickness": "tabletop thickness at an undamaged spot (mm); the reference that scales both photos",
    "chip_depth": "from the top surface down to the bottom of the chip, at the corner (mm)",
    "clearance": "gap between the piece and the break on every mating face (mm)",
}
OUTLINES = {  # from the photos (SAM 3.1), converted to mm by outlines_mm()
    "top": "outline of the missing area seen from above, [[x, y], ...] mm",
    "side": "outline of the missing area seen from the front face (y = 0), [[x, z], ...] mm",
}
MIN_FEATURE = 1.0  # break features narrower than this are flattened, so the gap there can exceed the clearance
E = 5.0  # how far the outlines are pushed past the table faces


def outlines_mm(shape, edge_thickness, chip_depth, **_):
    """SAM's outlines (0-1 image coords) -> mm in the table frame.

    The side photo's scale comes from the edge-thickness line. The point where the break meets the front edge is in
    both photos (top[1] and side[1]), which carries the scale to the top photo. The chip depth pins the side outline's
    height. Top photo: the corner is top-left, the front edge (x) runs down and the end edge (y) runs right, like the
    capture guide. Side photo: the front face, corner on the left, x right, z up.
    """
    # ponytail: assumes SAM's polygons already start at the corner; reorder them when SAM is wired
    def px(view):
        w, h = (float(v) for v in shape["size"][view])
        pts = [(float(u) * w, float(v) * h) for u, v in shape["outlines"][view]]
        if not (4 <= len(pts) <= 200 and w > 0 and h > 0):
            raise ValueError(f"{view} outline needs 4-200 points and a positive image size")
        return pts, w, h

    side, w, h = px("side")
    (a, b) = ((float(u) * w, float(v) * h) for u, v in shape["lines"]["edge_thickness"])
    s = edge_thickness / math.dist(a, b)  # mm per px in the side photo
    (cu, cv) = side[0]
    depth_px = max(v for _, v in side) - cv
    if depth_px <= 0 or side[1][0] <= cu:
        raise ValueError("side outline must start at the corner, run right along the top edge, then go down")
    side_mm = [((u - cu) * s, edge_thickness - (v - cv) * chip_depth / depth_px) for u, v in side]

    top, _, _ = px("top")
    st = side_mm[1][0] / math.dist(top[1], top[0])  # mm per px in the top photo
    (cu, cv) = top[0]
    top_mm = [((v - cv) * st, (u - cu) * st) for u, v in top]

    # Snap the corner and the two face points exactly onto the faces.
    top_mm[0], top_mm[1], top_mm[-1] = (0, 0), (top_mm[1][0], 0), (0, top_mm[-1][1])
    side_mm[0], side_mm[1], side_mm[-1] = (0, edge_thickness), (side_mm[1][0], edge_thickness), (0, side_mm[-1][1])
    out = {k: [[round(x, 2), round(y, 2)] for x, y in pts] for k, pts in (("top", top_mm), ("side", side_mm))}
    if not all(0 < max(abs(c) for p in pts for c in p) < 500 for pts in out.values()):
        raise ValueError("outline is out of range once scaled to mm")
    return out


def prisms(top, side, edge_thickness, chip_depth, clearance=0.2, flatten=True):
    """The top outline extruded vertically and the side outline extruded horizontally."""
    t, c, r = edge_thickness, clearance, (MIN_FEATURE / 2 if flatten else 0)
    # Push each outline's face points E past the table faces, so the offsets move only the break line.
    top = [(-E, -E), (top[1][0], -E), *map(tuple, top[1:]), (-E, top[-1][1])]
    side = [(-E, t + E), (side[1][0], t + E), *map(tuple, side[1:]), (-E, side[-1][1])]
    a = cq.Workplane("XY", origin=(0, 0, t - chip_depth - E)).polyline(top).close()
    b = cq.Workplane("XZ", origin=(0, -E, 0)).polyline(side).close()
    if c or r:
        a, b = (w.offset2D(-c - r).offset2D(r) if r else w.offset2D(-c) for w in (a, b))
    ymax = max(y for _, y in top)
    return a.extrude(chip_depth + 2 * E), b.extrude(-(ymax + 2 * E))  # XZ's normal is -y, so extrude negative


def _clip(solid, top, edge_thickness):
    xmax, ymax = max(x for x, _ in top), max(y for _, y in top)
    return solid.intersect(cq.Workplane().box(xmax + E, ymax + E, edge_thickness, centered=False))


def make(top, side, edge_thickness, chip_depth, clearance=0.2):
    a, b = prisms(top, side, edge_thickness, chip_depth, clearance)
    return _clip(a.intersect(b), top, edge_thickness)


def missing_solid(top, side, edge_thickness, chip_depth, **_):
    """The missing volume: both outlines as photographed, no clearance, nothing flattened."""
    a, b = prisms(top, side, edge_thickness, chip_depth, clearance=0, flatten=False)
    return _clip(a.intersect(b), top, edge_thickness)


def expected_bbox(**p):
    bb = make(**p).val().BoundingBox()
    return (bb.xlen, bb.ylen, bb.zlen)


def mating_solid(top, side, edge_thickness, chip_depth, **_):
    """The damaged table corner: a block four times the chip's size, with the missing volume cut out."""
    L = 4 * max(max(x for x, _ in top), max(y for _, y in top))
    block = cq.Workplane().box(L, L, edge_thickness, centered=False)
    return block.cut(missing_solid(top, side, edge_thickness, chip_depth))


def example():
    """The app's defaults in mock mode: mocks/diagnose.json's outlines and example measurements, make()'s clearance."""
    import json
    from pathlib import Path

    d = json.loads(json.loads((Path(__file__).parents[1] / "mocks" / "diagnose.json").read_text())[0]["content"])
    p = {m["key"]: float(m["example"]) for m in d["measurements"]} | {"clearance": 0.2}
    shape = {"outlines": d["outlines"], "size": d["size"], "lines": {m["key"]: m["line"] for m in d["measurements"]}}
    return p | outlines_mm(shape, **p)
