import type {
  ApiErrorPayload,
  MetricsHistoryResponse,
  MetricsResponse,
  ReadyResponse,
  ResourcesResponse,
  ScenarioOnInitSpec,
  WorkersResponse,
} from '../types/dashboard'

const DEFAULT_API_BASE_URL = ''

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/+$/, '')
}

const API_BASE_URL = normalizeBaseUrl(
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() ||
    DEFAULT_API_BASE_URL,
)

function extractErrorMessage(raw: string, fallback: string): string {
  if (!raw) {
    return fallback
  }
  try {
    const payload = JSON.parse(raw) as ApiErrorPayload
    const message = payload.error?.message
    if (typeof message === 'string' && message.trim().length > 0) {
      return message
    }
    return fallback
  } catch {
    return fallback
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  const raw = await response.text()
  const parsed = raw ? (JSON.parse(raw) as T) : ({} as T)
  if (!response.ok) {
    const fallbackMessage = `HTTP ${response.status} for ${path}`
    throw new Error(extractErrorMessage(raw, fallbackMessage))
  }
  return parsed
}

export async function fetchReady(): Promise<ReadyResponse> {
  return requestJson<ReadyResponse>('/ready')
}

export async function fetchWorkers(): Promise<WorkersResponse> {
  return requestJson<WorkersResponse>('/workers')
}

export async function fetchMetrics(options?: {
  count?: number
  includeEvents?: boolean
}): Promise<MetricsResponse> {
  const count = options?.count ?? 1
  const includeEvents = options?.includeEvents ?? true
  return requestJson<MetricsResponse>(
    `/metrics?count=${count}&include_events=${includeEvents ? 'true' : 'false'}`,
  )
}

export async function fetchMetricsHistory(
  range: '5m' | '15m' | '30m' | 'all',
  options?: { fromTs?: number },
): Promise<MetricsHistoryResponse> {
  const params = new URLSearchParams({ range })
  if (typeof options?.fromTs === 'number' && Number.isFinite(options.fromTs)) {
    params.set('from_ts', String(Math.max(0, Math.floor(options.fromTs))))
  }
  return requestJson<MetricsHistoryResponse>(`/metrics/history?${params.toString()}`)
}

export async function fetchResources(): Promise<ResourcesResponse> {
  return requestJson<ResourcesResponse>('/resources')
}

export async function fetchScenarioOnInitSpec(): Promise<ScenarioOnInitSpec> {
  return requestJson<ScenarioOnInitSpec>('/scenario/on_init_params')
}

export async function startTest(payload: {
  target_users: number
  init_params?: Record<string, unknown>
}): Promise<void> {
  await requestJson('/start_test', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function stopTest(): Promise<void> {
  await requestJson('/stop_test', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify({}),
  })
}

export async function changeUsers(payload: { target_users: number }): Promise<void> {
  await requestJson('/change_users', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function createResource(payload: {
  name: string
  count: number
  payload?: Record<string, unknown>
}): Promise<void> {
  await requestJson('/create_resource', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export { API_BASE_URL }
