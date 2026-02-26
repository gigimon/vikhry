export type TestState = 'IDLE' | 'PREPARING' | 'RUNNING' | 'STOPPING'

export interface ReadyResponse {
  ready: boolean
  state: TestState
  epoch: number
  alive_workers: number
  workers: string[]
}

export interface WorkersResponse {
  generated_at: number
  count: number
  workers: Array<{
    worker_id: string
    status: 'healthy' | 'unhealthy' | null
    last_heartbeat: number | null
    heartbeat_age_s: number | null
    users_count: number
    cpu_percent?: number | null
    memory_percent?: number | null
    rss_bytes?: number | null
    cpu_load?: number | null
    ram_load?: number | null
  }>
}

export interface ResourcesResponse {
  generated_at: number
  count: number
  resources: Array<{
    resource_name: string
    count: number
  }>
}

export interface MetricAggregate {
  window_s: number
  requests: number
  errors: number
  error_rate: number
  rps: number
  latency_avg_ms: number | null
  latency_median_ms: number | null
  latency_p95_ms: number | null
  latency_p99_ms: number | null
}

export interface MetricsResponse {
  generated_at: number
  lag: {
    detected: boolean
    metrics_with_backlog: string[]
    dropped_subscriber_messages: number
  }
  metrics: Array<{
    metric_id: string
    last_event_id: string | null
    aggregate: MetricAggregate
    events: Array<{
      event_id: string
      data: Record<string, unknown>
    }> | null
  }>
  count: number
  include_events: boolean
}

export interface StatsRow {
  name: string
  success: number
  failure: number
  medianMs: number | null
  p95Ms: number | null
  p99Ms: number | null
  averageMs: number | null
  rps: number
  failureRate: number
}

export interface ScenarioParam {
  name: string
  kind: 'positional_or_keyword' | 'keyword_only'
  required: boolean
  annotation: string | null
  default: unknown
}

export interface ScenarioOnInitSpec {
  configured: boolean
  scenario_path: string | null
  vu_class: string | null
  params: ScenarioParam[]
  accepts_arbitrary_kwargs: boolean
}

export interface ApiErrorPayload {
  error?: {
    code?: string
    message?: string
    details?: unknown
  }
}
