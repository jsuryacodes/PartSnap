# Steps 6 → 5 → 4 (simplified). Plan briefly, wait for my OK, then build in that order.

## Rules
- Build and test locally (vite dev pointing at the tunnel, or mock mode). Redeploy
  Vercel only after a step works — never mid-step.
- No live model calls from you except one tiny test per new call type; ask first.
- One commit + push per step.

## Step 6 — Spark Open review
Before STLs are released, Spark Open (Baseten, meta-models/muse-spark-open-1026)
reviews: verify results, Wonder's rationale, measurements, final dimensions.
Returns {verdict: "pass"|"concerns", notes} plus its real reasoning
(message.reasoning_content). Advisory only. Shown in the agent log with the
Spark Open tag.

## Step 5 — A/B/C on the user's own photos
From the SAM outlines, compute endpoints in code (no LLM coordinates):
- A on the front photo: feather tip → blunt end, along the edge.
- B on the top photo: deepest point, straight back from the edge.
- C on the front photo: deepest point, straight down from the edge.
Draw dimension lines + letters on the photos. Spark 1.3 writes the short label and
"why we need this" text. User types A/B/C in mm. Use the existing per-view scale
cross-check; warn on a big mismatch.

## Step 4 — capture
Photos 1 (top) and 2 (front): "Check photo" button (no live 2–3 s loop). The check
runs on Spark Open with text rules: straight above / straight on, chip centred and
in focus, no glare, no hand, close enough. Show Spark Open's real reasoning. Fail →
show the fix ("move closer"…). "Use anyway" after 2 fails. Cancel always visible.
Photo 3 (context): no check. Max 1 extra shot requested by Spark 1.3 with its
reason (diagnosis only, never geometry). Replace old "align corner" copy with
chip-on-edge wording.

## After all three
- Check the full flow at 390 px width (I screen-record on my phone).
- Make serve_public.sh self-healing (restart uvicorn/cloudflared if they exit;
  re-run the Vercel update if the URL changes; log to backend/.cache/serve/).
