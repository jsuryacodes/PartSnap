"""Run fix CadQuery code in a subprocess, check printability + fit, export STL (plus the mating object, for previews).

The code must assign a cadquery Workplane/Shape to `result`, in the fix module's frame. It runs with the fix's
SANDBOX helpers and its params as upper-case globals (TOP, FRONT, CLEARANCE, ...) already defined.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cadquery as cq
import trimesh

from fixes import FIXES

BBOX_TOL = 0.3  # mm
GAP_TOL = 0.05  # mm
TIMEOUT_S = 60
HERE = Path(__file__).parent
OUT_DIR = Path(os.getenv("OUT_DIR", HERE / "out"))  # a Modal Volume in production

# ponytail: subprocess + timeout + CPU rlimit + empty env (no API keys) is not a jail;
# swap for a container / Modal sandbox before running untrusted users' code at scale.
RUNNER = """
import json, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
sys.path.insert(0, sys.argv[3])
import cadquery as cq
ctx = json.load(open(sys.argv[2] + "/ctx.json"))
ns = {"cq": cq, **ctx["globals"]}
if ctx["module"]:
    import importlib
    mod = importlib.import_module(ctx["module"])
    ns.update({k: getattr(mod, k) for k in mod.SANDBOX})
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
    """Intersection volume, plus per mating face the gap: OCC distance from a point on the face to the piece's
    surface (point-to-shape; face-to-face extrema misreport parallel facets). Only faces facing the piece (their
    normal ray hits it) and within its length count; the rest are open sides or past the trimmed ends."""
    interference = piece.intersect(mating).Volume()
    bb, skin = piece.BoundingBox(), cq.Compound.makeCompound(piece.Faces())
    gaps, skipped = [], 0
    for f in mating.Faces():
        p = _on_face(f)
        if not bb.xmin <= p.x <= bb.xmax:
            skipped += 1
            continue
        n = f.normalAt(p)
        if piece.intersect(cq.Edge.makeLine(p, p + n * 1000)).Edges():
            gaps.append({"face": _face_label(n), "x": round(p.x, 2), "area": round(f.Area(), 2),
                         "gap": round(cq.Vertex.makeVertex(*p.toTuple()).distance(skin), 3)})
    return interference, gaps, skipped


def _typical(gaps):
    """Area-weighted median: the gap most of the mating surface sees."""
    half, acc = sum(g["area"] for g in gaps) / 2, 0
    for g in sorted(gaps, key=lambda g: g["gap"]):
        acc += g["area"]
        if acc >= half:
            return g["gap"]


def _run(code, mod, params, tmp):
    """Run the code in the sandbox; returns an error string or None (part.step / part.stl written to tmp)."""
    (Path(tmp) / "fix.py").write_text(code)
    glob = {k.upper(): v for k, v in params.items() if k != "trimmed_mm"}
    if hasattr(mod, "MIN_THICKNESS"):
        glob["MIN_THICKNESS"] = mod.MIN_THICKNESS
    (Path(tmp) / "ctx.json").write_text(json.dumps(
        {"globals": glob, "module": mod.__name__ if hasattr(mod, "SANDBOX") else None}))
    try:
        p = subprocess.run([sys.executable, "-I", "-c", RUNNER, "fix.py", tmp, str(HERE)],
                           cwd=tmp, env={"PATH": "/usr/bin:/bin", "HOME": tmp},
                           capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"timed out after {TIMEOUT_S}s"
    if p.returncode != 0:
        return p.stderr[-2000:] or f"exit code {p.returncode}"


def verify(code: str, fix: str, params: dict, out_dir=OUT_DIR) -> dict:
    """params: the fix's params (for chip_fill also the mm outlines, and trimmed_mm the agent declared).
    Returns {"ok", "error", "checks": [{"name", "ok", "value", "expected"}], ...measurements, stl_path, mate_path}."""
    mod = FIXES[fix]
    c = params["clearance"]
    res = {"ok": False, "error": None, "clearance": c, "checks": []}
    with tempfile.TemporaryDirectory() as tmp:
        err = _run(code, mod, params, tmp)
        if err:
            res["error"] = err
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
        inter, res["gaps"], res["gaps_skipped"] = fit_check(piece, mating)
        res["interference_volume"] = round(inter, 6)
        gs = [g["gap"] for g in res["gaps"]]
        res["gap"] = {"min": min(gs), "typical": _typical(res["gaps"]), "max": max(gs)} if gs else None
        if hasattr(mod, "thickness_profile"):
            xs, th = mod.thickness_profile(mesh.vertices, mesh.faces, step=0.05)
            i = int(th.argmin())
            res["min_thickness"], res["thinnest_at_x"] = round(float(th[i]), 3), round(float(xs[i]), 2)
            untrimmed = mod.expected_bbox(**{**params, "trimmed_mm": 0})[0]
            res["trimmed_mm"] = round(untrimmed - bb.xlen, 2)

        problems, checks = [], res["checks"]

        def check(name, ok, value, expected=None, problem=None):
            checks.append({"name": name, "ok": bool(ok), "value": value, "expected": expected})
            if not ok:
                problems.append(problem)

        body = res["watertight"] and res["bodies"] == 1 and res["volume"] > 0
        check("Watertight, single body", body, f"{res['bodies']} body" if res["watertight"] else "open mesh", None,
              f"mesh is {'watertight' if res['watertight'] else 'NOT watertight'} with {res['bodies']} bodies, "
              f"volume {res['volume']} mm³: expected one closed solid")
        hints = getattr(mod, "BBOX_HINTS", ("",) * 3)
        off = [f"bbox {a} is {got} mm, expected {exp} ± {BBOX_TOL}" + (f" ({h})" if h else "")
               for a, got, exp, h in zip(AXES, res["bbox"], res["expected_bbox"], hints) if abs(got - exp) > BBOX_TOL]
        check("Overall size", not off, " × ".join(f"{v:.2f}" for v in res["bbox"]) + " mm",
              " × ".join(f"{v:.2f}" for v in res["expected_bbox"]) + f" ± {BBOX_TOL}", "; ".join(off))
        check("Overlap with the table", res["interference_volume"] <= 1e-6, f"{res['interference_volume']:.3f} mm³", "0",
              f"piece overlaps the table by {res['interference_volume']:.3f} mm³: check placement and the clearance offset")
        bad = sorted((g for g in res["gaps"] if abs(g["gap"] - c) > GAP_TOL), key=lambda g: abs(g["gap"] - c), reverse=True)
        if not gs:
            check("Gap to the break", False, "no faces", f"{c:.2f} ± {GAP_TOL}",
                  "piece does not face any mating face: check placement in the frame")
        else:
            worst = "; ".join(f"{g['gap']:.3f} mm at x = {g['x']}" for g in bad[:3])
            check("Gap to the break", not bad, f"{res['gap']['typical']:.3f} mm typical",
                  f"{c:.2f} ± {GAP_TOL} on {len(gs)} faces ({res['gap']['min']:.3f}–{res['gap']['max']:.3f})",
                  f"gap is off by more than {GAP_TOL} mm on {len(bad)} of {len(gs)} mating faces, expected {c} "
                  f"(worst: {worst})")
        if "min_thickness" in res:
            m = mod.MIN_THICKNESS
            check("Min thickness", res["min_thickness"] >= m - 0.02, f"{res['min_thickness']:.2f} mm", f"≥ {m}",
                  f"piece is {res['min_thickness']} mm thick at x = {res['thinnest_at_x']}, expected ≥ {m}: trim the thin ends")
        if problems:
            res["error"] = "; ".join(problems)
            return res

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256((code + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:12]
        stl = Path(out_dir) / f"{fix}-{h}-{round(c * 100):03d}.stl"  # params in the hash: agent code is generic
        shutil.copy(Path(tmp) / "part.stl", stl)
        mate = stl.with_name(f"{fix}-{h}-mate.stl")
        cq.exporters.export(mating, str(mate), tolerance=0.05, angularTolerance=0.2)
        res.update(ok=True, stl_path=str(stl), mate_path=str(mate))
    return res


if __name__ == "__main__":  # offline self-check: known-good / known-bad agent code, no model calls
    import inspect

    from fixes import chip_fill, corner_cap

    from string import Template
    mock = json.loads(Template((HERE / "mocks" / "wonder_cad_chip_fill.json").read_text()).safe_substitute(trimmed_mm=0))
    bad_code, good_code = (json.loads(e["content"])["code"] for e in mock)
    for c in (0.2, 0.4):
        p = chip_fill.example(clearance=c)
        good = verify(good_code, "chip_fill", p)
        print(f"chip_fill good c={c}:", json.dumps({k: v for k, v in good.items() if k not in ("gaps", "checks")}))
        assert good["ok"], good["error"]
        assert good["interference_volume"] == 0 and abs(good["gap"]["typical"] - c) < 0.01 and good["min_thickness"] >= 1
        stl = trimesh.load(good["stl_path"])
        assert abs(stl.bounds[0][2]) < 1e-6 and stl.bounds[1][2] > 0, "tabletop face (z = 0) on the print bed"

    p = chip_fill.example()
    nooffset = verify(bad_code, "chip_fill", p)
    assert not nooffset["ok"] and "gap" in nooffset["error"] and "bbox" in nooffset["error"], nooffset["error"]
    lie = verify(good_code, "chip_fill", p | {"trimmed_mm": 1.0})  # right part, wrong declared trim
    assert not lie["ok"] and "bbox x" in lie["error"], lie["error"]
    # A generic wedge with the right envelope must not pass: the chip is irregular.
    x0, y, z = good["expected_bbox"]
    wedge = (f"result = cq.Workplane('YZ').polyline([(0, 0), ({y}, 0), (0, {z})]).close().extrude({x0})"
             f".translate((1, 0, 0))\n")
    w = verify(wedge, "chip_fill", p)
    assert not w["ok"] and ("overlap" in w["error"] or "gap" in w["error"]), w["error"]
    crash = verify("result = loft_between(TOP)\n", "chip_fill", p)
    assert not crash["ok"] and "TypeError" in crash["error"], crash["error"]
    print("chip_fill bad cases caught:", nooffset["error"][:160], "|", w["error"][:120])

    q = dict(edge_thickness=18, reach_x=40, reach_y=40, wall=2.5, clearance=0.2)
    src = inspect.getsource(corner_cap)
    good = verify(src + f"\nresult = make(**{q!r})\n", "corner_cap", q)
    assert good["ok"], good["error"]
    assert {g["face"]: g["gap"] for g in good["gaps"]} == {"-x": 0.2, "-y": 0.2, "-z": 0.2, "+z": 0.2}, good["gaps"]
    tight = verify(src + f"\nresult = make(**{ {**q, 'clearance': -0.5}!r})\n", "corner_cap", q)
    assert not tight["ok"] and tight["interference_volume"] > 0, tight
    loose = verify(src + f"\nresult = make(**{ {**q, 'clearance': 0.5}!r})\n", "corner_cap", q)
    assert not loose["ok"] and "gap" in loose["error"], loose
    print("verify self-check passed")
