"""Run fix CadQuery code in a subprocess, check printability + fit, export STL (plus the mating object, for previews).

The code must assign a cadquery Workplane/Shape to `result`, in the fix module's frame.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cadquery as cq
import trimesh

from fixes import FIXES

BBOX_TOL = 0.2  # mm
GAP_TOL = 0.1  # mm
FILL_MIN = 0.90  # piece volume / missing volume, for fixes that replace what broke off
TIMEOUT_S = 60
OUT_DIR = Path(os.getenv("OUT_DIR", Path(__file__).parent / "out"))  # a Modal Volume in production

# ponytail: subprocess + timeout + CPU rlimit + empty env (no API keys) is not a jail;
# swap for a container / Modal sandbox before running untrusted users' code at scale.
RUNNER = """
import resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
import cadquery as cq
ns = {}
exec(open(sys.argv[1]).read(), ns)
r = ns.get("result")
if r is None:
    sys.exit("code must assign the final cadquery Workplane/Shape to `result`")
cq.exporters.export(r, sys.argv[2] + "/part.step")
cq.exporters.export(r, sys.argv[2] + "/part.stl", tolerance=0.01, angularTolerance=0.1)
"""

AXES = "xyz"


def _face_label(n):
    i = max(range(3), key=lambda k: abs(n.toTuple()[k]))
    return ("+" if n.toTuple()[i] > 0 else "-") + AXES[i]


def _on_face(f):
    """A point on the face: the centroid of its largest triangle (a break face's centre of mass can lie off it)."""
    vs, tris = f.tessellate(0.1)
    a, b, c = max(([vs[i] for i in t] for t in tris), key=lambda q: (q[1] - q[0]).cross(q[2] - q[0]).Length)
    return (a + b + c) / 3


def fit_check(piece, mating):
    """Intersection volume, plus the gap along each mating face's outward normal, as [{face, gap, area}].
    Faces whose normal ray never hits the piece are open sides and are skipped."""
    interference = piece.intersect(mating).Volume()
    gaps = []
    for f in mating.Faces():
        p = _on_face(f)
        n = f.normalAt(p)
        hit = piece.intersect(cq.Edge.makeLine(p, p + n * 1000))
        if hit.Edges():
            gaps.append({"face": _face_label(n), "gap": round(cq.Vertex.makeVertex(*p.toTuple()).distance(hit), 3),
                         "area": round(f.Area(), 1)})
    return interference, gaps


def _typical(gaps):
    """Area-weighted median: the gap most of the mating surface sees, not a few flattened slivers."""
    half, acc = sum(g["area"] for g in gaps) / 2, 0
    for g in sorted(gaps, key=lambda g: g["gap"]):
        acc += g["area"]
        if acc >= half:
            return g["gap"]


def verify(code: str, fix: str, params: dict, out_dir=OUT_DIR) -> dict:
    mod = FIXES[fix]
    res = {"ok": False, "error": None}
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "fix.py").write_text(code)
        try:
            p = subprocess.run(
                [sys.executable, "-I", "-c", RUNNER, "fix.py", tmp],
                cwd=tmp, env={"PATH": "/usr/bin:/bin", "HOME": tmp},
                capture_output=True, text=True, timeout=TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            res["error"] = f"timed out after {TIMEOUT_S}s"
            return res
        if p.returncode != 0:
            res["error"] = p.stderr[-2000:] or f"exit code {p.returncode}"
            return res

        mesh = trimesh.load(Path(tmp) / "part.stl")
        piece = cq.importers.importStep(str(Path(tmp) / "part.step")).val()
        mating = mod.mating_solid(**params).val()
        bb = piece.BoundingBox()
        res["watertight"] = bool(mesh.is_watertight)
        res["bodies"] = len(mesh.split(only_watertight=False))
        res["volume"] = round(float(mesh.volume), 3)
        res["bbox"] = [round(v, 3) for v in (bb.xlen, bb.ylen, bb.zlen)]
        res["expected_bbox"] = [round(v, 3) for v in mod.expected_bbox(**params)]
        res["interference_volume"], res["gaps"] = fit_check(piece, mating)
        res["interference_volume"] = round(res["interference_volume"], 6)
        gs = [g["gap"] for g in res["gaps"]]
        res["gap"] = {"min": min(gs), "typical": _typical(res["gaps"]), "max": max(gs)} if gs else None
        if hasattr(mod, "missing_solid"):
            res["fill_ratio"] = round(piece.Volume() / mod.missing_solid(**params).val().Volume(), 4)

        clearance = params["clearance"]
        problems = []
        if not res["watertight"]:
            problems.append("mesh is not watertight")
        if res["bodies"] != 1:
            problems.append(f"expected 1 body, got {res['bodies']}")
        if res["volume"] <= 0:
            problems.append("non-positive volume")
        for a, got, exp in zip(AXES, res["bbox"], res["expected_bbox"]):
            if abs(got - exp) > BBOX_TOL:
                problems.append(f"bbox {a} is {got} mm, expected {exp} ± {BBOX_TOL}")
        if res["interference_volume"] > 1e-6:
            problems.append(f"piece intersects the mating object ({round(res['interference_volume'], 2)} mm³): check placement and offsets")
        if not res["gaps"]:
            problems.append("piece does not touch any mating face: check placement in the frame")
        else:
            # Fixes that flatten small break features may sit looser there; nothing may sit tighter.
            loose_ok = getattr(mod, "MIN_FEATURE", 0)
            bad = sorted((g for g in res["gaps"] if g["gap"] < clearance - GAP_TOL
                          or (not loose_ok and g["gap"] > clearance + GAP_TOL)), key=lambda g: g["gap"])
            problems += [f"gap on {g['face']} face is {g['gap']} mm, expected {clearance} ± {GAP_TOL}" for g in bad[:3]]
            if len(bad) > 3:
                problems.append(f"{len(bad) - 3} more mating faces are off by more than {GAP_TOL} mm")
            if abs(res["gap"]["typical"] - clearance) > GAP_TOL:
                problems.append(f"typical gap is {res['gap']['typical']} mm, expected {clearance} ± {GAP_TOL}")
        if not FILL_MIN <= res.get("fill_ratio", 1) <= 1:  # over 100% means it sticks out of the chip or into the wood
            problems.append(f"fill ratio is {res['fill_ratio']:.1%}, expected {FILL_MIN:.0%}-100% of the missing volume")
        if problems:
            res["error"] = "; ".join(problems)
            return res

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        stl = Path(out_dir) / f"{fix}-{hashlib.sha256(code.encode()).hexdigest()[:12]}.stl"
        shutil.copy(Path(tmp) / "part.stl", stl)
        mate = stl.with_name(stl.stem + "-mate.stl")
        cq.exporters.export(mating, str(mate), tolerance=0.05, angularTolerance=0.2)
        res.update(ok=True, stl_path=str(stl), mate_path=str(mate))
    return res


if __name__ == "__main__":
    import inspect
    import json

    from fixes import chip_fill, corner_cap

    q = chip_fill.example()
    assert q["top"][1] == [26.0, 0] and q["side"][1] == [26.0, 18.0], q  # scale carried from the side photo to the top
    src = inspect.getsource(chip_fill)
    fill = verify(src + f"\nresult = make(**{q!r})\n", "chip_fill", q)
    print("chip_fill:", json.dumps({k: v for k, v in fill.items() if k != "gaps"}, indent=2))
    assert fill["ok"], fill["error"]
    assert fill["interference_volume"] == 0 and fill["gap"]["min"] >= 0.19 and fill["gap"]["typical"] == 0.2, fill["gap"]
    assert 0.9 <= fill["fill_ratio"] < 1, fill["fill_ratio"]
    grown = verify(src.replace("offset2D(-c - r).offset2D(r)", "offset2D(c + r).offset2D(-r)")
                   + f"\nresult = make(**{q!r})\n", "chip_fill", q)
    assert not grown["ok"] and grown["interference_volume"] > 0 and grown["fill_ratio"] > 1, grown

    p = dict(edge_thickness=18, reach_x=40, reach_y=40, wall=2.5, clearance=0.2)
    src = inspect.getsource(corner_cap)

    good = verify(src + f"\nresult = make(**{p!r})\n", "corner_cap", p)
    print("corner_cap:", json.dumps({k: v for k, v in good.items() if k != "gaps"}, indent=2))
    assert good["ok"], good["error"]
    assert {g["face"]: g["gap"] for g in good["gaps"]} == {"-x": 0.2, "-y": 0.2, "-z": 0.2, "+z": 0.2}, good["gaps"]

    tight = verify(src + f"\nresult = make(**{ {**p, 'clearance': -0.5}!r})\n", "corner_cap", p)
    assert not tight["ok"] and tight["interference_volume"] > 0, tight

    loose = verify(src + f"\nresult = make(**{ {**p, 'clearance': 0.5}!r})\n", "corner_cap", p)
    assert not loose["ok"] and "gap" in loose["error"], loose

    broken = verify("result = cq.Workplane().box(1, 1, 1)\n", "corner_cap", p)
    assert not broken["ok"] and "NameError" in broken["error"], broken

    print("verify self-check passed")
