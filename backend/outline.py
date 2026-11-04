"""Chip outline: a SAM 3.1 mask, or the user's taps, as a simplified polygon in original-photo pixels.
Every outline has the same shape whatever its source:
    {"polygon": [[x, y], ...], "area_px", "bbox": [x1, y1, x2, y2], "image_size": [w, h], "source": "sam"|"tap", "score"}
"""
import io

import numpy as np
from PIL import Image, ImageDraw, ImageOps

import models

MAX_PX = 1024  # SAM input size; outline precision matters, so not smaller
PROMPTS = ("exposed particleboard", "chipped wood edge")  # tried in order, stop at the first plausible mask
AREA_RANGE = (0.001, 0.15)  # plausible chip area as a fraction of the photo (rejects "the whole table")
TOLERANCE_PX = 1.0  # simplification tolerance in SAM-image px; small so the break stays irregular


def prep_image(data: bytes, max_px: int = MAX_PX) -> tuple[bytes, tuple[int, int], tuple[float, float]]:
    """(upright JPEG downscaled for SAM, original upright size, (x, y) original px per SAM px)."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    size = im.size
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue(), size, (size[0] / im.size[0], size[1] / im.size[1])


def _rdp(pts: np.ndarray, tol: float) -> np.ndarray:
    """Ramer-Douglas-Peucker on an open polyline."""
    a, b = pts[0], pts[-1]
    if len(pts) < 3:
        return pts
    ab, ap = b - a, pts[1:-1] - a
    d = np.abs(ab[0] * ap[:, 1] - ab[1] * ap[:, 0]) / (np.hypot(*ab) or 1.0)
    i = int(np.argmax(d)) + 1
    if d[i - 1] <= tol:
        return np.array([a, b])
    return np.vstack([_rdp(pts[:i + 1], tol)[:-1], _rdp(pts[i:], tol)])


def simplify(ring, tol: float = TOLERANCE_PX) -> np.ndarray:
    """Closed ring -> fewer points, none more than `tol` px off the original. Split at the point
    farthest from the start so both halves are open polylines."""
    pts = np.asarray(ring, float)
    far = int(np.argmax(np.hypot(*(pts - pts[0]).T)))
    return np.vstack([_rdp(pts[:far + 1], tol)[:-1], _rdp(np.vstack([pts[far:], pts[:1]]), tol)[:-1]])


def _area(pts) -> float:
    x, y = np.asarray(pts, float).T
    return 0.5 * float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def from_polygon(polygon, image_size, source: str, score: float | None = None) -> dict:
    pts = np.asarray(polygon, float)
    return {"polygon": [[round(float(x), 1), round(float(y), 1)] for x, y in pts], "area_px": round(_area(pts), 1),
            "bbox": [round(float(v), 1) for v in (*pts.min(0), *pts.max(0))], "image_size": list(image_size),
            "source": source, "score": score}


def from_taps(points, image_size) -> dict:
    """User-tapped polygon (original-photo px) -> outline. Raises ValueError on bad input."""
    w, h = image_size
    if not 3 <= len(points) <= 500:
        raise ValueError("need 3 to 500 points")
    if any(len(p) != 2 or not (0 <= p[0] <= w and 0 <= p[1] <= h) for p in points):
        raise ValueError("every point must be [x, y] inside the image")
    if _area(points) < 1:
        raise ValueError("points don't enclose an area")
    return from_polygon(points, image_size, "tap")


def _plausible(objects, sam_size):
    """Best-scoring mask whose area is a plausible chip, else None."""
    total = sam_size[0] * sam_size[1]
    ok = [o for o in objects if AREA_RANGE[0] <= o["mask"].sum() / total <= AREA_RANGE[1] and o["contours"]]
    return max(ok, key=lambda o: o["score"] or 0, default=None)


def find_chip(photo: bytes, point: tuple | None = None, prompts=PROMPTS, use_point: bool = True,
              mock: str = "sam", timeout: int = 300) -> dict:
    """Text prompts in order, then (if use_point) a positive point at `point` (original-photo px;
    the user's tap) or the photo centre. Stops at the first plausible mask.
    Returns {"outline": outline or None, "attempts": [{"prompt", "matches": [{"score", "area_frac"}], "accepted"}]}."""
    img, size, scale = prep_image(photo)
    tries = [{"text": t} for t in prompts]
    if use_point:
        x, y = point or (size[0] / 2, size[1] / 2)
        tries.append({"points": [(x / scale[0], y / scale[1], True)]})
    attempts = []
    for kw in tries:
        res = models.sam(img, mock=mock, timeout=timeout, **kw)
        total = res["image_size"][0] * res["image_size"][1]
        best = _plausible(res["objects"], res["image_size"])
        attempts.append({"prompt": kw.get("text") or f"point {tuple(round(v) for v in kw['points'][0][:2])}",
                         "matches": [{"score": o["score"], "area_frac": round(o["mask"].sum() / total, 4)}
                                     for o in res["objects"]],
                         "accepted": best is not None, "usage": res["usage"]})
        if best:
            ring = max(best["contours"], key=_area)
            return {"outline": from_polygon(simplify(ring) * np.array(scale), size, "sam", best["score"]), "attempts": attempts}
    return {"outline": None, "attempts": attempts}


def save_overlay(photo: bytes, outline: dict | None, path, label: str = "") -> None:
    """Debug PNG: the outline (safety orange) and its bbox drawn on the upright photo."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(photo))).convert("RGB")
    d = ImageDraw.Draw(im)
    if outline:
        d.rectangle(outline["bbox"], outline=(80, 160, 255), width=1)
        d.line([tuple(p) for p in outline["polygon"] + outline["polygon"][:1]], fill=(255, 102, 0), width=2)
        x1, y1 = outline["bbox"][:2]
        d.text((x1, max(0, y1 - 14)), f"{label} {outline['source']} score={outline['score']} "
                                      f"area={outline['area_px']:.0f}px pts={len(outline['polygon'])}", fill=(255, 102, 0))
    else:
        d.text((10, 10), f"{label} no plausible mask", fill=(255, 0, 0))
    im.save(path)


if __name__ == "__main__":  # offline self-check (MOCK_MODE): no network
    import tempfile
    from pathlib import Path

    assert models.MOCK_MODE, "run with MOCK_MODE=1"
    sq = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10), (5, 10.2), (0, 10), (0, 5)]
    assert len(simplify(sq, 0.5)) == 4 and len(simplify(sq, 0.1)) == 5  # collinear points go, the bump stays

    buf = io.BytesIO()
    Image.new("RGB", (1204, 1600), (20, 20, 20)).save(buf, "JPEG")
    photo = buf.getvalue()
    for view in ("top", "front"):
        r = find_chip(photo, mock=f"sam_{view}")
        o = r["outline"]
        assert o and o["source"] == "sam" and len(r["attempts"]) == 1, r["attempts"]
        assert AREA_RANGE[0] < o["area_px"] / (1204 * 1600) < AREA_RANGE[1] and len(o["polygon"]) >= 8, o
        assert all(0 <= x <= 1204 and 0 <= y <= 1600 for x, y in o["polygon"])
        if view == "top":  # the mock's higher-scoring "whole table" match must lose to the chip
            assert [m["area_frac"] > AREA_RANGE[1] for m in r["attempts"][0]["matches"]] == [True, False]
        save_overlay(photo, o, Path(tempfile.mkdtemp()) / "o.png", view)

    t = from_taps([[10, 10], [110, 10], [60, 90]], (1204, 1600))
    assert set(t) == set(o) and t["area_px"] == 4000 and t["bbox"] == [10, 10, 110, 90], t
    for bad in ([[1, 1], [2, 2]], [[1, 1], [2, 2], [5000, 3]], [[1, 1], [2, 2], [3, 3]]):
        try:
            from_taps(bad, (1204, 1600))
            raise AssertionError(bad)
        except ValueError:
            pass
    print("outline self-check passed")
