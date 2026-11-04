export const API = import.meta.env.VITE_API_URL ?? '/api'

export type View = 'top' | 'side' | 'closeup'
export type Photos = Record<View, Blob>

/** Backend errors carry a human-readable `detail` (rate limit, daily budget, bad input). */
async function errorOf(r: Response) {
  const text = await r.text()
  try { return new Error(JSON.parse(text).detail) } catch { return new Error(`${r.status}: ${text}`) }
}

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const r = await fetch(API + path, { method: 'POST', body: form })
  if (!r.ok) throw await errorOf(r)
  return r.json()
}

export async function checkPhoto(view: View, photo: Blob) {
  const f = new FormData()
  f.append('view', view)
  f.append('photo', photo, `${view}.jpg`)
  return postForm<{ ok: boolean; retake_instruction: string | null; rationale?: string | null; reasoning?: string | null; by: string }>('/check-photo', f)
}

type Pt = [number, number]
export type Measurement = { key: string; letter?: string; label: string; hint: string; photo: View; line: [Pt, Pt]; example?: number }
export type Diagnosis = {
  fix_type: string
  title: string
  explanation: string
  rationale?: string
  outlines: Partial<Record<View, Pt[]>> // SAM 3.1, 0–1 image coordinates (side = the front face)
  measurements: Measurement[] // where to measure: lines computed from SAM's outlines, not by the LLM
  extent_px?: { top: [number, number]; front: [number, number] } // chip's [along, across] edge extent, photo px
  settings: Record<string, number>
  param_help: Record<string, string>
  shape: unknown // passed back to /generate untouched; the backend turns the outlines into mm
  by: { diagnosis: string; segmentation: string }
}

export async function diagnose(photos: Photos) {
  const f = new FormData()
  for (const [view, blob] of Object.entries(photos)) f.append(view, blob, `${view}.jpg`)
  return postForm<Diagnosis>('/diagnose', f)
}

export type Check = { name: string; ok: boolean; value: string; expected: string | null }
export type VerifyResult = {
  ok: boolean
  error: string | null
  clearance: number
  checks: Check[] // the inspector's rows, exactly as backend/verify.py judged them
  bbox?: number[]
  gap?: { min: number; typical: number; max: number } | null
  gaps?: { gap: number; x: number }[]
  interference_volume?: number
  min_thickness?: number
  trimmed_mm?: number
}
export type Usage = { prompt_tokens?: number | null; completion_tokens?: number | null; reasoning_tokens?: number | null }
export type Verdict = 'approve' | 'reject' | 'unavailable'
export type Stl = { clearance: number; url: string }
export type GenEvent =
  | { type: 'attempt'; n: number; by: string }
  | { type: 'design'; n: number; model: string; by: string; rationale?: string; code?: string; code_hash?: string
      trimmed_mm?: number; usage: Usage; error?: string }
  | ({ type: 'verify'; n: number } & VerifyResult)
  | { type: 'review'; run: string; verdict: Verdict; notes: string[]; reasoning?: string | null; usage: Usage; by: string }
  | { type: 'done'; ok: boolean; attempts: number; model?: string; rationale?: string; trimmed_mm?: number
      stls?: Stl[]; mate_url?: string; review?: Verdict; run?: string }
  | { type: 'error'; message: string }

/** POST + read the server-sent event stream (EventSource can't POST). */
export async function generate(fix: string, params: Record<string, number>, shape: unknown, onEvent: (e: GenEvent) => void) {
  const r = await fetch(API + '/generate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ fix, params, shape }),
  })
  if (!r.ok || !r.body) throw await errorOf(r)
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += value
    const chunks = buf.split('\n\n')
    buf = chunks.pop()!
    for (const c of chunks) if (c.startsWith('data: ')) onEvent(JSON.parse(c.slice(6)))
  }
}

/** Puts "downloaded despite the review's reject" on the record in the backend's agent log. */
export async function reviewOverride(run: string) {
  const r = await fetch(API + '/review-override', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ run }) })
  if (!r.ok) throw await errorOf(r)
}
