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
