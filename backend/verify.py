"""Run fix CadQuery code in a subprocess, check printability + fit, export STL.

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


def fit_check(cap, mating):
    """Intersection volume, plus the gap along each mating face's outward normal.
    Faces whose normal ray never hits the cap are open sides and are skipped."""
    interference = cap.intersect(mating).Volume()
    gaps = {}
    for f in mating.Faces():
        p = f.Center()
        n = f.normalAt(p)
        hit = cap.intersect(cq.Edge.makeLine(p, p + n * 1000))
        if hit.Edges():
            gaps[_face_label(n)] = round(cq.Vertex.makeVertex(*p.toTuple()).distance(hit), 4)
    return interference, gaps


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
        cap = cq.importers.importStep(str(Path(tmp) / "part.step")).val()
        bb = cap.BoundingBox()
        res["watertight"] = bool(mesh.is_watertight)
        res["bodies"] = len(mesh.split(only_watertight=False))
        res["volume"] = round(float(mesh.volume), 3)
        res["bbox"] = [round(v, 3) for v in (bb.xlen, bb.ylen, bb.zlen)]
        res["expected_bbox"] = [round(v, 3) for v in mod.expected_bbox(**params)]
        res["interference_volume"], res["gaps"] = fit_check(cap, mod.mating_solid(**params).val())
        res["interference_volume"] = round(res["interference_volume"], 6)

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
            problems.append(f"cap intersects the mating object ({res['interference_volume']} mm³); check placement in the frame")
        if not res["gaps"]:
            problems.append("cap does not touch any mating face; check placement in the frame")
        for face, g in res["gaps"].items():
            if abs(g - clearance) > GAP_TOL:
                problems.append(f"gap on {face} face is {g} mm, expected {clearance} ± {GAP_TOL}")
        if problems:
            res["error"] = "; ".join(problems)
            return res

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        stl = Path(out_dir) / f"{fix}-{hashlib.sha256(code.encode()).hexdigest()[:12]}.stl"
        shutil.copy(Path(tmp) / "part.stl", stl)
        res.update(ok=True, stl_path=str(stl))
    return res


if __name__ == "__main__":
    import inspect
    import json

    from fixes import corner_cap

    p = dict(edge_thickness=18, reach_x=40, reach_y=40, wall=2.5, clearance=0.2)
    src = inspect.getsource(corner_cap)

    good = verify(src + f"\nresult = make(**{p!r})\n", "corner_cap", p)
    print("good:", json.dumps(good, indent=2))
    assert good["ok"], good["error"]
    assert set(good["gaps"]) == {"-x", "-y", "-z", "+z"}, good["gaps"]

    tight = verify(src + f"\nresult = make(**{ {**p, 'clearance': -0.5}!r})\n", "corner_cap", p)
    assert not tight["ok"] and tight["interference_volume"] > 0, tight

    loose = verify(src + f"\nresult = make(**{ {**p, 'clearance': 0.5}!r})\n", "corner_cap", p)
    assert not loose["ok"] and "gap" in loose["error"], loose

    broken = verify("result = cq.Workplane().box(1, 1, 1)\n", "corner_cap", p)
    assert not broken["ok"] and "NameError" in broken["error"], broken

    print("verify self-check passed")
