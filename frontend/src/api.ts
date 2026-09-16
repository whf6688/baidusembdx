export type Envelope<T> = {
  request_id: string
  status: string
  data: T
  data_at?: string
  snapshot_watermark?: string
  error?: { code: string; message: string }
}

export class ApiRequestError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(message: string, status: number, code: string | null = null) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
  }
}

const BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export type LocalIdentity = {
  username: 'local-admin' | 'wang_kang' | 'wang_cong'
  role: 'admin' | 'operator'
}

export type EffectiveIdentity = {
  username: string
  role: 'admin' | 'operator'
}

const LOCAL_IDENTITY_KEY = 'search-console.local-identity'
const REQUESTED_ROLE_KEY = 'search-console.requested-role'
const DEFAULT_IDENTITY: LocalIdentity = { username: 'local-admin', role: 'admin' }
let serverIdentity: EffectiveIdentity | null = null

export function getLocalIdentity(): LocalIdentity {
  try {
    const saved = JSON.parse(localStorage.getItem(LOCAL_IDENTITY_KEY) || 'null') as { username?: unknown } | null
    if (saved?.username === 'wang_kang' || saved?.username === 'wang_cong') return { username: saved.username, role: 'operator' }
    if (saved?.username === '王康') return { username: 'wang_kang', role: 'operator' }
    if (saved?.username === '王聪') return { username: 'wang_cong', role: 'operator' }
    if (saved?.username === 'local-admin') return DEFAULT_IDENTITY
  } catch {
    // Ignore damaged local development preferences and fall back to admin.
  }
  return DEFAULT_IDENTITY
}

export function setLocalIdentity(identity: LocalIdentity): void {
  localStorage.setItem(LOCAL_IDENTITY_KEY, JSON.stringify(identity))
}

export function getRequestedRole(): 'admin' | 'operator' {
  return localStorage.getItem(REQUESTED_ROLE_KEY) === 'admin' ? 'admin' : 'operator'
}

export function setRequestedRole(role: 'admin' | 'operator'): void {
  localStorage.setItem(REQUESTED_ROLE_KEY, role)
}

export function setServerIdentity(identity: EffectiveIdentity): void {
  serverIdentity = identity
}

export function getEffectiveIdentity(): EffectiveIdentity {
  return serverIdentity || getLocalIdentity()
}

function authHeaders(json = false): Record<string, string> {
  const identity = getLocalIdentity()
  return {
    ...(json ? { 'content-type': 'application/json' } : {}),
    'x-user': identity.username,
    'x-role': identity.role,
    'x-requested-role': getRequestedRole(),
  }
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (typeof item === 'string') return item
      if (!item || typeof item !== 'object') return null
      const row = item as { msg?: unknown; message?: unknown; loc?: unknown }
      const message = typeof row.msg === 'string' ? row.msg.replace(/^Value error,\s*/i, '') : typeof row.message === 'string' ? row.message : null
      return message
    }).filter((message): message is string => Boolean(message))
    return messages.length ? [...new Set(messages)].join('；') : null
  }
  if (detail && typeof detail === 'object') {
    const row = detail as { msg?: unknown; message?: unknown; detail?: unknown }
    if (typeof row.message === 'string') return row.message
    if (typeof row.msg === 'string') return row.msg.replace(/^Value error,\s*/i, '')
    return detailMessage(row.detail)
  }
  return null
}

async function readResponse<T>(response: Response, notifyAuthenticationFailure = true): Promise<T> {
  let body: Envelope<T> & { detail?: unknown }
  try {
    body = (await response.json()) as Envelope<T> & { detail?: unknown }
  } catch {
    throw new ApiRequestError(`请求失败（${response.status}）`, response.status)
  }
  if (!response.ok || body.status === 'error') {
    if (notifyAuthenticationFailure && response.status === 401) window.dispatchEvent(new Event('search-console:auth-required'))
    throw new ApiRequestError(
      body.error?.message || detailMessage(body.detail) || `请求失败（${response.status}）`,
      response.status,
      body.error?.code || null,
    )
  }
  return body.data
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    signal,
    headers: authHeaders(),
  })
  return readResponse<T>(response)
}

/** Re-check the current browser session without recursively raising the global login event. */
export async function probeSession<T>(signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}/session`, {
    signal,
    headers: authHeaders(),
  })
  return readResponse<T>(response, false)
}

export async function apiPost<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    signal,
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  })
  return readResponse<T>(response)
}

export async function apiPatch<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    signal,
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  })
  return readResponse<T>(response)
}

export async function apiPut<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    signal,
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  })
  return readResponse<T>(response)
}

export async function apiDelete<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'DELETE',
    signal,
    headers: authHeaders(),
  })
  return readResponse<T>(response)
}

export async function apiUpload<T>(path: string, file: File, fields: Record<string, string> = {}, signal?: AbortSignal): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  Object.entries(fields).forEach(([name, value]) => form.append(name, value))
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST', signal,
    headers: authHeaders(),
    body: form,
  })
  return readResponse<T>(response)
}

export async function apiDownload(path: string): Promise<void> {
  const response = await fetch(`${BASE}${path}`, {
    headers: authHeaders(),
  })
  if (!response.ok) throw new Error(`导出失败（${response.status}）`)
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  const disposition = response.headers.get('content-disposition') || ''
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const fallbackName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  anchor.download = encodedName ? decodeURIComponent(encodedName) : fallbackName || 'report.csv'
  anchor.click()
  URL.revokeObjectURL(href)
}

export function isAuthenticationError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 401
}
