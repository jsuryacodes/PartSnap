"""Corner cap: L-shaped cap that slides over a chipped tabletop corner.

Frame (mm): the table corner vertex is at the origin and the tabletop occupies
x >= 0, y >= 0, 0 <= z <= edge_thickness. The cap wraps the two end faces
(x = 0, y = 0) plus the top and bottom, and is open toward +x and +y.
"""
import cadquery as cq

PARAMS = {
    "edge_thickness": "tabletop thickness at the edge (mm)",
    "reach_x": "how far the cap extends from the corner along the X edge (mm)",
    "reach_y": "how far the cap extends from the corner along the Y edge (mm)",
    "wall": "cap wall thickness (mm)",
    "clearance": "gap between cap and table on every mating face (mm)",
}


def _box(x0, y0, z0, x1, y1, z1):
    return cq.Workplane().box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def make(edge_thickness, reach_x, reach_y, wall=2.0, clearance=0.2):
    t, c, w = edge_thickness, clearance, wall
    outer = _box(-c - w, -c - w, -c - w, reach_x, reach_y, t + c + w)
    pocket = _box(-c, -c, -c, reach_x + 1, reach_y + 1, t + c)  # +1 overshoot avoids coplanar cut faces
    return outer.cut(pocket)


def expected_bbox(edge_thickness, reach_x, reach_y, wall=2.0, clearance=0.2):
    c, w = clearance, wall
    return (reach_x + c + w, reach_y + c + w, edge_thickness + 2 * (c + w))


def mating_solid(edge_thickness, reach_x, reach_y, **_):
    """The table corner the cap fits over."""
    return _box(0, 0, 0, reach_x, reach_y, edge_thickness)
