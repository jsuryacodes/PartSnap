export const API = import.meta.env.VITE_API_URL ?? '/api'

export type View = 'top' | 'side' | 'closeup'
export type Photos = Record<View, Blob>

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const r = await fetch(API + path, { method: 'POST', body: form })
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function checkPhoto(view: View, photo: Blob) {
  const f = new FormData()
  f.append('view', view)
  f.append('photo', photo, `${view}.jpg`)
  return postForm<{ ok: boolean; retake_instruction: string | null; by: string }>('/check-photo', f)
}

type Pt = [number, number]
export type Measurement = { key: string; label: string; hint: string; photo: View; line: [Pt, Pt]; example?: number }
export type Diagnosis = {
  fix_type: string
  title: string
  explanation: string
  damage?: { photo: View; polygon: Pt[] }
  measurements: Measurement[]
  settings: Record<string, number>
  param_help: Record<string, string>
  by: { diagnosis: string; segmentation: string }
}

export async function diagnose(photos: Photos) {
  const f = new FormData()
  for (const [view, blob] of Object.entries(photos)) f.append(view, blob, `${view}.jpg`)
  return postForm<Diagnosis>('/diagnose', f)
}

export type VerifyResult = {
  ok: boolean
  error: string | null
  watertight?: boolean
  bodies?: number
  bbox?: number[]
  expected_bbox?: number[]
  interference_volume?: number
  gaps?: Record<string, number>
}
export type GenEvent =
  | { type: 'attempt'; n: number; by: string }
  | { type: 'code'; n: number; reasoning: string | null; code: string }
  | ({ type: 'verify'; n: number } & VerifyResult)
  | { type: 'done'; ok: boolean; attempts: number; stl_url?: string }

/** POST + read the server-sent event stream (EventSource can't POST). */
export async function generate(fix: string, params: Record<string, number>, onEvent: (e: GenEvent) => void) {
  const r = await fetch(API + '/generate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ fix, params }),
  })
  if (!r.ok || !r.body) throw new Error(`/generate: ${r.status} ${await r.text()}`)
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
