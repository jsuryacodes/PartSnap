"""Chip fill: the missing piece of a chipped table edge, lofted between the chip's outlines in a top and a front photo.

Frame (mm): origin at the chip's right (blunt) end, on the table's top front edge. x runs LEFT along the edge (the
feather end is at x = edge length), y runs back into the table from the front face (y = 0), z runs DOWN into the
table from the tabletop (z = 0). The table is y >= 0, z >= 0, so every chip coordinate is positive, and the exported
STL lies with its tabletop face (z = 0) flat on the print bed and the glue face up: no supports.

Outlines come from SAM in photo px (outline.py). Top photo: the front edge runs along the bottom, level. Front photo:
the top edge runs along the top, level. Same left-right in both, blunt end on the right. outlines_mm() scales each
view per axis: along the edge by edge_length_mm, across it by that view's depth, both anchored at the right end.

Helpers (also callable from the agent's code in the verify sandbox, see SANDBOX):
  loft_between(top_back, front_bottom)  the missing piece: a ruled surface from the back boundary of the top outline
                                        ([x, y] points) to the bottom boundary of the front outline ([x, z] points)
  offset_inward(solid, clearance)       moves the break surface in by `clearance` (true 3D offset); the tabletop and
                                        front faces stay flush
  enforce_min_thickness(solid, min_mm)  cuts thin ends off; returns (solid, trimmed_mm), trimmed_mm along x
  mating_solid(top, front)              the damaged table: a block with the chip cut out
Thickness, here and in verify: in each cross-section x = const, the distance from the piece's outer corner (the
table's edge line, y = z = 0) to its glue face.
"""
import json
from functools import lru_cache
from pathlib import Path

import cadquery as cq
import manifold3d as m3
import numpy as np
import trimesh

PARAMS = {
    "edge_length_mm": "length of the chip along the edge, from the blunt end to the feather tip (mm)",
    "top_depth_mm": "on the tabletop: how far the chip reaches back from the edge, at its deepest (mm)",
    "front_depth_mm": "on the front face: how far the chip reaches down from the edge, at its deepest (mm)",
    "clearance": "gap between the piece and the break, 0.2 or 0.4 (mm)",
}
MIN_THICKNESS = 1.0
SANDBOX = ("loft_between", "offset_inward", "enforce_min_thickness", "mating_solid")
BBOX_HINTS = ("edge length minus the clearance at both ends minus trimmed_mm",
              "top depth minus the clearance, measured square to the sloped break",
              "front depth minus the clearance, measured square to the sloped break")
STEP = 0.1  # thickness stations along the edge (mm)
MARGIN = 0.05  # stations must clear min_mm by this much, so the piece between them does too
FLAT = 1e-5  # a facet lying on the tabletop (z = 0) or the front face (y = 0) is flush, not glue


def outlines_mm(shape, edge_length_mm, top_depth_mm, front_depth_mm, **_):
    """SAM outlines {"top": outline, "front": outline} (photo px) -> {"top": [[x, y], ...], "front": [[x, z], ...]} mm,
    plus each view's mm/px along and across the edge (a big mismatch means an angled photo or a typo)."""
    # ponytail: assumes the edge is level in each photo (hero roll <= 0.8 deg, <= 0.2 mm); fit the edge line if not
    def view(name, depth_down, depth_mm):
        p = np.asarray(shape[name]["polygon"], float)
        if p.ndim != 2 or p.shape[1] != 2 or not 4 <= len(p) <= 500:
            raise ValueError(f"{name} outline needs 4-500 [x, y] points")
        along = p[:, 0].max() - p[:, 0]
        across = p[:, 1] - p[:, 1].min() if depth_down else p[:, 1].max() - p[:, 1]
        if along.max() <= 0 or across.max() <= 0:
            raise ValueError(f"{name} outline is flat")
        s = edge_length_mm / along.max(), depth_mm / across.max()
        return np.c_[along * s[0], across * s[1]].round(4).tolist(), [round(float(v), 5) for v in s]

    top, st = view("top", False, top_depth_mm)
    front, sf = view("front", True, front_depth_mm)
    return {"top": top, "front": front, "scale": {"top": st, "front": sf}}


MEASURE = {  # what the user measures with a ruler, and on which photo the app draws it
    "edge_length_mm": ("A", "front"),  # feather tip -> blunt end, along the edge
    "top_depth_mm": ("B", "top"),  # edge -> deepest point, straight back
    "front_depth_mm": ("C", "front"),  # edge -> deepest point, straight down
}


def dimension_lines(shape):
    """SAM outlines (photo px, the frames above) -> {key: {"letter", "photo", "line": [[x, y], [x, y]] (0-1)}} plus
    "extent_px": {view: [along, across]} for the scale cross-check. Computed from the outlines, never by an LLM."""
    t, f = (np.asarray(shape[v]["polygon"], float) for v in ("top", "front"))
    (tw, th), (fw, fh) = shape["top"]["image_size"], shape["front"]["image_size"]
    edge_t, edge_f = t[:, 1].max(), f[:, 1].min()  # top photo: edge along the bottom; front photo: along the top
    deep_t, deep_f = t[t[:, 1].argmin()], f[f[:, 1].argmax()]
    lines = {"edge_length_mm": [[f[:, 0].min(), edge_f], [f[:, 0].max(), edge_f]],
             "top_depth_mm": [[deep_t[0], edge_t], deep_t.tolist()],
             "front_depth_mm": [[deep_f[0], edge_f], deep_f.tolist()]}
    norm = {"top": (tw, th), "front": (fw, fh)}
    out = {k: {"letter": MEASURE[k][0], "photo": MEASURE[k][1],
               "line": [[round(x / norm[MEASURE[k][1]][0], 4), round(y / norm[MEASURE[k][1]][1], 4)] for x, y in ln]}
           for k, ln in lines.items()}
    out["extent_px"] = {"top": [float(np.ptp(t[:, 0])), float(edge_t - t[:, 1].min())],
                        "front": [float(np.ptp(f[:, 0])), float(f[:, 1].max() - edge_f)]}
    return out


def _envelope(pts, xs, closed):
    """Deepest point of a polyline (or closed outline) at each x: the boundary farthest from the edge."""
    p = np.asarray(pts, float)
    a, b = (p, np.roll(p, -1, 0)) if closed else (p[:-1], p[1:])
    dx = b[:, 0] - a[:, 0]
    vert = np.abs(dx) < 1e-9
    X = np.asarray(xs, float)[:, None]
    inside = (X >= np.minimum(a[:, 0], b[:, 0]) - 1e-9) & (X <= np.maximum(a[:, 0], b[:, 0]) + 1e-9)
    t = (X - a[:, 0]) / np.where(vert, 1, dx)
    d = np.where(vert, np.maximum(a[:, 1], b[:, 1]), a[:, 1] + t * (b[:, 1] - a[:, 1]))
    return np.maximum(np.where(inside, d, 0).max(1), 0.05)  # clamp: a zero-area section breaks the loft


def _solid(V, T):
    """Planar-facet cq.Solid, carrying its mesh so the next helper needn't re-tessellate."""
    V, T = np.asarray(V, float), np.asarray(T)
    faces = [cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(*V[i]) for i in t], close=True)) for t in T]
    s = cq.Solid.makeSolid(cq.Shell.makeShell(faces)).fix()
    s._mesh = V, T  # ponytail: lost on any cq transform; _mesh() then tessellates (exact for planar facets, slower)
    return s


def _mesh(solid):
    s = solid.val() if isinstance(solid, cq.Workplane) else solid
    if hasattr(s, "_mesh"):
        return s._mesh
    V, T = s.tessellate(1e-3)
    key, inv = np.unique(np.round([v.toTuple() for v in V], 6), axis=0, return_inverse=True)
    return key, inv.reshape(-1)[np.asarray(T)]


def _manifold(V, T):
    mk = lambda tri: m3.Manifold(m3.Mesh(vert_properties=np.asarray(V, np.float32), tri_verts=np.asarray(tri, np.uint32)))
    m = mk(T)
    if m.status() != m3.Error.NoError or m.volume() < 0:
        m = mk(np.asarray(T)[:, ::-1])
    if m.status() != m3.Error.NoError:
        raise ValueError(f"not a closed solid ({m.status()})")
    return m


def _from_manifold(m):
    if m.is_empty():
        raise ValueError("nothing left of the piece")
    mm = m.to_mesh()
    return _solid(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts))


def _box(x0, y0, z0, x1, y1, z1):
    return m3.Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def _loft(top, front, closed):
    xs = np.unique(np.round(np.r_[np.asarray(top, float)[:, 0], np.asarray(front, float)[:, 0]], 4))
    b, f = _envelope(top, xs, closed), _envelope(front, xs, closed)
    # Keep only stations where a boundary bends: extra stations on straight stretches would re-split the twisted
    # facets differently, so the same boundaries picked two ways would give surfaces ~0.1 mm apart.
    bent = lambda d: np.abs(d[1:-1] - (d[:-2] + (d[2:] - d[:-2]) * (xs[1:-1] - xs[:-2]) / (xs[2:] - xs[:-2]))) > 1e-4
    keep = np.r_[True, bent(b) | bent(f), True]
    xs, b, f = xs[keep], b[keep], f[keep]
    # Right-triangle section at every station: edge corner, back point on the tabletop, bottom point on the front.
    V = np.array([q for x, bb, ff in zip(xs, b, f) for q in ((x, 0, 0), (x, bb, 0), (x, 0, ff))])
    n, T = len(xs), []
    for i in range(n - 1):
        for k in range(3):  # each side of the section sweeps a quad: 2 planar facets
            a, c = 3 * i + k, 3 * (i + 1) + (k + 1) % 3
            T += [(a, 3 * i + (k + 1) % 3, c), (a, c, 3 * (i + 1) + k)]
    T += [(0, 2, 1), (3 * n - 3, 3 * n - 2, 3 * n - 1)]
    m = _manifold(V, T)
    return _from_manifold(m)


def loft_between(top_back, front_bottom):
    """The missing piece: a ruled surface from the top outline's back boundary ([x, y] polyline, ordered along x) to
    the front outline's bottom boundary ([x, z] polyline), closed by the tabletop and front faces. Each section across
    the edge is a right triangle; between stations the break is 2 planar facets, so every point of both boundaries
    is kept. Where a polyline doubles back, the deepest point at each x counts."""
    if len(top_back) < 2 or len(front_bottom) < 2:
        raise ValueError("each boundary needs at least 2 points")
    return _loft(top_back, front_bottom, closed=False)


def offset_inward(solid, clearance):
    """True 3D offset: every point of the break surface moves `clearance` mm into the piece. The tabletop (z = 0) and
    front (y = 0) faces stay flush, and the chip's end walls move in too."""
    if clearance <= 0:
        return solid
    V, T = _mesh(solid)
    lo, hi, e = V.min(0), V.max(0), 3.0
    # Erode the piece plus the air over the tabletop and in front of the face: only the table (the break) pushes in.
    air = _box(lo[0] - e, -e, -e, hi[0] + e, 0, hi[2] + e) + _box(lo[0] - e, -e, -e, hi[0] + e, hi[1] + e, 0)
    eroded = (_manifold(V, T) + air).minkowski_difference(m3.Manifold.sphere(clearance, 32))  # inscribed: <= 0.002 under
    return _from_manifold(eroded ^ _box(lo[0] - e, 0, 0, hi[0] + e, hi[1] + e, hi[2] + e))


def thickness_profile(V, T, step=STEP, inset=0.01):
    """(xs, thickness at each x): in the cross-section x = const, distance from the outer corner (x, 0, 0) to the
    glue face (every facet not flush with the tabletop or the front face)."""
    V, T = np.asarray(V, float), np.asarray(T)
    tri = V[T]
    glue = ~(np.all(np.abs(tri[..., 1]) < FLAT, 1) | np.all(np.abs(tri[..., 2]) < FLAT, 1))
    g = trimesh.Trimesh(V, T[glue], process=False)
    xs = np.arange(V[:, 0].min() + inset, V[:, 0].max() - inset + 1e-9, step)
    out = []
    for x in xs:
        seg = trimesh.intersections.mesh_plane(g, (1, 0, 0), (x, 0, 0))
        if not len(seg):
            out.append(0.0)
            continue
        a, d = seg[:, 0, 1:], seg[:, 1, 1:] - seg[:, 0, 1:]
        t = np.clip(-np.einsum("ij,ij->i", a, d) / np.maximum(np.einsum("ij,ij->i", d, d), 1e-12), 0, 1)
        out.append(float(np.linalg.norm(a + t[:, None] * d, axis=1).min()))
    return xs, np.array(out)


def enforce_min_thickness(solid, min_mm=MIN_THICKNESS):
    """Cut the thin ends off (the feather end, and the tip of the blunt end) so every cross-section is at least
    min_mm thick. Keeps the longest stretch that is, cut flat at both ends. Returns (solid, trimmed_mm along x)."""
    V, T = _mesh(solid)
    lo, hi = V[:, 0].min(), V[:, 0].max()
    xs, th = thickness_profile(V, T)
    ok = np.flatnonzero(th >= min_mm + MARGIN)
    if not len(ok):
        raise ValueError(f"the piece is thinner than {min_mm} mm everywhere (thickest {th.max():.2f} mm)")
    run = max(np.split(ok, np.flatnonzero(np.diff(ok) > 1) + 1), key=len)
    a = lo if run[0] == 0 else xs[run[0]]
    b = hi if run[-1] == len(xs) - 1 else xs[run[-1]]
    if a == lo and b == hi:
        return solid, 0.0
    cut = _manifold(V, T) ^ _box(a, -1, -1, b, V[:, 1].max() + 1, V[:, 2].max() + 1)
    return _from_manifold(cut), round(float((hi - lo) - (b - a)), 3)


def missing_solid(top, front, **_):
    """The chip as photographed: the reference loft between the full outlines' deepest boundaries."""
    return _loft(top, front, closed=True)


def mating_solid(top, front, **_):
    """The damaged table around the chip: a block with the missing piece cut out."""
    m = missing_solid(top, front)
    bb = m.BoundingBox()
    block = cq.Solid.makeBox(bb.xlen + 6, bb.ymax + 3, bb.zmax + 3, cq.Vector(bb.xmin - 3, 0, 0))
    return cq.Workplane().add(block.cut(m))


@lru_cache(maxsize=16)
def _reference(key):
    top, front, clearance = json.loads(key)
    piece = offset_inward(missing_solid(top, front), clearance)
    pre = piece.BoundingBox()
    out, trimmed = enforce_min_thickness(piece)
    bb = out.BoundingBox()
    return {"piece": out, "pre_len": pre.xlen, "trimmed_mm": trimmed,
            "blunt_mm": round(bb.xmin - pre.xmin, 2), "feather_mm": round(pre.xmax - bb.xmax, 2)}


def reference(top, front, clearance=0.2, **_):
    """The deterministic build: what the helpers make from the full outlines. Verify's yardstick."""
    return _reference(json.dumps([top, front, clearance]))


def make(top, front, edge_length_mm, top_depth_mm, front_depth_mm, clearance=0.2):
    """The reference piece (cq.Workplane), trimmed to MIN_THICKNESS."""
    return cq.Workplane().add(reference(top, front, clearance)["piece"])


def expected_bbox(top, front, clearance=0.2, trimmed_mm=None, **_):
    """x: the length after the clearance minus trimmed_mm (the reference trim if not given); y, z: the reference
    piece's, i.e. the measured depths minus the clearance measured square to the sloped break."""
    r = reference(top, front, clearance)
    bb = r["piece"].BoundingBox()
    return r["pre_len"] - (r["trimmed_mm"] if trimmed_mm is None else trimmed_mm), bb.ylen, bb.zlen


def example(edge_length_mm=18.0, top_depth_mm=5.0, front_depth_mm=3.5, clearance=0.2):
    """Params for the hero chip: SAM's saved outlines (no network) and the given measurements
    (defaults are placeholders; the real ones live in samples/hero/measurements.json)."""
    import models
    import outline
    hero = Path(__file__).resolve().parents[2] / "samples" / "hero"
    was, models.MOCK_MODE = models.MOCK_MODE, True
    try:
        shape = {v: outline.find_chip((hero / f"{v}.jpeg").read_bytes(), use_point=False, mock=f"sam_{v}")["outline"]
                 for v in ("top", "front")}
    finally:
        models.MOCK_MODE = was
    p = {"edge_length_mm": edge_length_mm, "top_depth_mm": top_depth_mm, "front_depth_mm": front_depth_mm,
         "clearance": clearance}
    return p | outlines_mm(shape, **p)


if __name__ == "__main__":  # offline self-check on the hero outlines: no model calls
    import time

    import outline
    hero = Path(__file__).resolve().parents[2] / "samples" / "hero"
    shape = {v: outline.find_chip((hero / f"{v}.jpeg").read_bytes(), use_point=False, mock=f"sam_{v}")["outline"]
             for v in ("top", "front")}
    dl = dimension_lines(shape)
    for k, (letter, view) in MEASURE.items():
        (x0, y0), (x1, y1) = dl[k]["line"]
        assert dl[k]["letter"] == letter and all(0 <= v <= 1 for v in (x0, y0, x1, y1)), dl[k]
        assert (y0 == y1 and x1 > x0) if letter == "A" else (x0 == x1 and y0 != y1), dl[k]  # along / square to edge
    hm = json.loads((hero / "measurements.json").read_text())
    s = outlines_mm(shape, **hm)["scale"]  # dimension lines and outlines_mm must agree on the px extents
    assert abs(hm["edge_length_mm"] / dl["extent_px"]["front"][0] - s["front"][0]) < 1e-4, (dl["extent_px"], s)
    assert abs(hm["top_depth_mm"] / dl["extent_px"]["top"][1] - s["top"][1]) < 1e-4, (dl["extent_px"], s)
    ratios = {v: s[v][0] / s[v][1] for v in s}
    print(f"dimension lines ok; hero along/across mm-per-px ratio {ratios} (UI warns beyond 1.4x)")

    for c in (0.2, 0.4):
        t0 = time.time()
        p = example(clearance=c)
        top, front = p["top"], p["front"]
        assert min(x for x, _ in top) == 0 == min(x for x, _ in front), "anchored at the right end"
        assert abs(max(x for x, _ in top) - 18) < 1e-3 and abs(max(y for _, y in top) - 5) < 1e-3
        assert abs(max(z for _, z in front) - 3.5) < 1e-3

        M = missing_solid(top, front)
        bb = M.BoundingBox()
        assert M.isValid() and max(abs(bb.xlen - 18), abs(bb.ylen - 5), abs(bb.zlen - 3.5)) < 1e-3, bb.__dict__

        P = offset_inward(M, c)
        pb = P.BoundingBox()
        assert P.isValid() and abs(pb.xmin - c) < 0.01 and abs(pb.xmax - (18 - c)) < 0.01, (pb.xmin, pb.xmax)
        assert abs(pb.zmin) < 1e-6 and abs(pb.ymin) < 1e-6, "flush with the tabletop and the front face"
        # Offset exactness: a point on each break facet is `c` from the piece (OCC point-to-shape distance).
        faces = cq.Compound.makeCompound(P.Faces())
        flush = lambda f: all(abs(v.Y) < FLAT for v in f.Vertices()) or all(abs(v.Z) < FLAT for v in f.Vertices())
        gaps = [cq.Vertex.makeVertex(*f.Center().toTuple()).distance(faces) for f in M.Faces()
                if not flush(f) and pb.xmin + 1 < f.Center().x < pb.xmax - 1]
        assert len(gaps) > 30 and all(abs(g - c) < 0.006 for g in gaps), (min(gaps), max(gaps))

        piece, trimmed = enforce_min_thickness(P)
        qb = piece.BoundingBox()
        xs, th = thickness_profile(*piece._mesh, step=0.05)
        assert th.min() >= MIN_THICKNESS - 0.02, th.min()
        assert abs((pb.xlen - qb.xlen) - trimmed) < 1e-6 and qb.xmin > pb.xmin and qb.xmax < pb.xmax, "trims both ends"
        assert piece.intersect(mating_solid(top, front).val()).Volume() < 1e-6
        r = reference(top, front, c)
        print(f"c={c}: scale {p['scale']}; piece {qb.xlen:.2f} x {qb.ylen:.3f} x {qb.zlen:.3f} mm, "
              f"trimmed {trimmed} (blunt {r['blunt_mm']}, feather {r['feather_mm']}), gaps {min(gaps):.4f}-"
              f"{max(gaps):.4f}, min thickness {th.min():.3f}, {time.time() - t0:.1f}s")
        assert abs(qb.zlen - 3.5) < 2 * c and abs(qb.ylen - 5) < 2.2 * c  # sloped break: 1.3c and 2c here
    print("chip_fill self-check passed")
