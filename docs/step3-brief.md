# PartSnap — Step 3: Muse Wonder CAD design + verify/repair loop

## Status
Step 2 (SAM 3.1 outlines) is done and accepted as is. Both hero outlines are good;
do NOT modify outline geometry.

## Housekeeping (one commit, before Step 3)
1. outline.py: use "chipped wood edge" as the only text prompt (drop
   "exposed particleboard" — it found nothing on both photos).
2. Strip EXIF (including GPS) from samples/hero/*.jpeg, then commit samples/hero
   (photos + out/ overlays). The repo is public.

## Goal
Muse Wonder turns the measured chip into a CadQuery fix. The verify loop checks it;
failures go back to Wonder for repair. Done = one hero run produces a watertight,
correctly sized part that passes all checks, exported as two STLs.

## Process
Enter plan mode, post the plan, wait for my approval. Commit + push per sub-step.

## Inputs
- Outline points for top and front views (from Step 2 / the saved mocks).
- samples/hero/measurements.json, hand-entered:
  {"edge_length_mm": ..., "top_depth_mm": ..., "front_depth_mm": ..., "source": "hand-measured"}
  Create it with placeholder nulls; I'll fill the real values. Step 3 must not
  depend on Step 5 (measurement overlays).
- Clearance setting: 0.2 or 0.4 mm.

## View alignment + scale
- Per-view px→mm scale from measurements.json.
- Both views anchor at the RIGHT (blunt) chip end along the edge axis. The left
  feather end gets trimmed anyway.

## Deterministic helpers (write these yourself, test offline, no model calls)
Available inside the CadQuery sandbox:
- loft_between(top_boundary_pts_mm, front_boundary_pts_mm) — loft/ruled surface
  from the back boundary of the top outline to the bottom boundary of the front
  outline (NOT an intersection of two extrusions).
- offset_inward(solid, clearance)
- enforce_min_thickness(solid, 1.0) -> (solid, trimmed_mm) — trims the feather edge.
- mating_solid(...) — the damaged-chip volume from the same outlines, used by verify.

## Design call (Muse Wonder)
- Model: muse-wonder-1.0. On error, fall back ONCE to muse-spark-1.3; log which was used.
- Wonder writes the CadQuery that calls the helpers: picks the boundary segments,
  sets parameters, handles trimming, and repairs on failure. Fix type restricted to
  chip_fill; no free-form CAD from scratch.
- Output schema (reject anything that doesn't parse; count as a failed attempt):
  {"code": string, "rationale": string, "fix_type": "chip_fill", "trimmed_mm": number}
- Add the same user-facing "rationale" field to Spark 1.3 JSON outputs too. Meta models
  return no raw reasoning, so this is what the UI shows.

## Verify loop (sandboxed CadQuery, no model calls)
- Watertight.
- Bounding box: compare against measured dims minus 2×clearance on each mating face,
  and front depth minus trimmed_mm. Tolerance ±0.3 mm on top of that.
- Overlap check against mating_solid.
- Per-face gap at the chosen clearance: measure on the B-rep (OCC distance), not the
  STL mesh, ±0.05 mm. If B-rep isn't practical, use mesh at ±0.1 mm and tell me.
- Min thickness 1.0 mm.
- Any failure: send error text + failing code back to Wonder for repair.
- Max 3 repair attempts. If all fail, show the failure and agent log. No silent
  fallback, no fake pass.
- Only if all checks pass: export two STLs, 0.2 mm and 0.4 mm clearance.

## Logging + UI
- Log each attempt: model used, code hash, failed check, rationale, token counts.
- Agent log shows verify failures and repairs as they happen (the demo's visible
  "thinking").

## Testing
- Offline first: run the verify loop on one known-good and one known-bad CadQuery
  file; confirm the checks catch the bad one. Test the helpers on the hero outlines.
- Keep MOCK_MODE=1 until offline tests pass.
- Live: ONE Wonder design call and at most one repair cycle, via a script, one call
  at a time. Ask me before any re-run.

## Out of scope
Capture flow rework (Step 4), measurement overlays (Step 5), Spark Open review (Step 6).

## Risks
Wonder may return valid but wrong geometry. Overlap + gap checks catch some of it;
the printed part is the final check. Keep the chip shape irregular so a generic
shape can't pass by accident.

## Working rules (unchanged)
- Never read or stage backend/.env.
- Live calls only via scripts: tiny prompts, ~150 max output tokens (raise only for
  the Wonder code call — tell me the number you pick), 60 s timeout, images downscaled.
- Effort: Max for the plan, helpers and verify math; High for everything else.
