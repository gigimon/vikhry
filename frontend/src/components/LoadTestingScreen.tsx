import {
  Activity,
  ChevronDown,
  Clock3,
  Columns3,
  Gauge,
  Layers,
  Play,
  Square,
  Users,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import {
  changeUsers,
  createResource,
  fetchMetrics,
  fetchMetricsHistory,
  fetchReady,
  fetchResources,
  fetchScenarioOnInitSpec,
  fetchWorkers,
  startTest,
  stopTest,
} from '../api/dashboardApi'
import { ProbeChartsPanel } from './ProbeChartsScreen'
import { ResourceCreateModal } from './ResourceCreateModal'
import { ResourceViewModal } from './ResourceViewModal'
import type {
  MetricsHistoryResponse,
  MetricsResponse,
  ReadyResponse,
  ResourcesResponse,
  ScenarioOnInitSpec,
  StatsRow,
  WorkersResponse,
} from '../types/dashboard'

const REFRESH_INTERVAL_MS = 1_000
const ERROR_EVENTS_FETCH_COUNT = 1000

type TabId = 'statistics' | 'charts' | 'probes' | 'errors' | 'resources' | 'workers'
type StatsScope = 'window' | 'total'
type StatsColumnId =
  | 'name'
  | 'success'
  | 'failure'
  | 'medianMs'
  | 'p95Ms'
  | 'p99Ms'
  | 'averageMs'
  | 'rps'
  | 'failureRate'
type LatencySeriesId = 'averageMs' | 'medianMs' | 'p95Ms' | 'p99Ms'
type ChartRangeId = '5m' | '15m' | '30m' | 'all'
type NotificationTone = 'info' | 'success' | 'error'

interface ChartHistoryPoint {
  ts: number
  totalUsers: number | null
  rpsByMetric: Record<string, number>
  latencyByMetric: Record<string, Record<LatencySeriesId, number | null>>
}

interface ChartMetricOption {
  id: string
  source: string
}

interface NotificationItem {
  id: number
  tone: NotificationTone
  message: string
}

interface SourceBreakdownRow {
  source: string
  requests: number
  errors: number
  fatal: number
}

interface ErrorBreakdownSnapshot {
  totalRequests: number
  totalErrors: number
  totalFatal: number
  resultCodeRows: Array<{ label: string; count: number }>
  resultCategoryRows: Array<{ label: string; count: number }>
  sourceRows: SourceBreakdownRow[]
}

interface TracebackRow {
  key: string
  metricId: string
  source: string
  stage: string
  category: string
  errorType: string | null
  errorMessage: string | null
  traceback: string
  eventId: string
  timestampMs: number | null
}

const tabs: Array<{ id: TabId; label: string }> = [
  { id: 'statistics', label: 'Statistics' },
  { id: 'charts', label: 'Charts' },
  { id: 'probes', label: 'Probes' },
  { id: 'errors', label: 'Errors' },
  { id: 'resources', label: 'Resources' },
  { id: 'workers', label: 'Workers' },
]

const statsColumns: Array<{ id: StatsColumnId; label: string; required?: boolean }> = [
  { id: 'name', label: 'Name', required: true },
  { id: 'success', label: 'Success' },
  { id: 'failure', label: 'Failure' },
  { id: 'medianMs', label: 'Median (ms)' },
  { id: 'p95Ms', label: 'P95 (ms)' },
  { id: 'p99Ms', label: 'P99 (ms)' },
  { id: 'averageMs', label: 'Average (ms)' },
  { id: 'rps', label: 'RPS' },
  { id: 'failureRate', label: 'Failure Rate' },
]

const defaultVisibleColumns = statsColumns.map((column) => column.id)
const NOTIFICATION_TTL_MS = 4_500
const ERROR_NOTIFICATION_TTL_MS = 7_000
const rpsLinePalette = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
const latencySeriesMeta: Array<{ id: LatencySeriesId; label: string; color: string }> = [
  { id: 'averageMs', label: 'Average', color: '#8b5cf6' },
  { id: 'medianMs', label: 'Median', color: '#22c55e' },
  { id: 'p95Ms', label: 'P95', color: '#f59e0b' },
  { id: 'p99Ms', label: 'P99', color: '#ef4444' },
]
const chartRanges: Array<{ id: ChartRangeId; label: string }> = [
  { id: '5m', label: '5 minutes' },
  { id: '15m', label: '15 minutes' },
  { id: '30m', label: '30 minutes' },
  { id: 'all', label: 'All time' },
]
const chartRangeToSeconds: Record<Exclude<ChartRangeId, 'all'>, number> = {
  '5m': 5 * 60,
  '15m': 15 * 60,
  '30m': 30 * 60,
}

const numberFormatter = new Intl.NumberFormat('en-US')
const compactNumberFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 1,
})
const gigabytesFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 1,
})
const BYTES_IN_MB = 1024 * 1024
const BYTES_IN_GB = 1024 * 1024 * 1024

function formatMaybeNumber(value: number | null, fractionDigits = 0): string {
  if (value === null || Number.isNaN(value)) {
    return '—'
  }
  return value.toFixed(fractionDigits)
}

function formatElapsed(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

function failureRateStyle(rate: number): React.CSSProperties | undefined {
  if (rate <= 0) return undefined
  // 10% steps: 0.1 → lightest red, 1.0 → strongest red
  const pct = Math.min(rate, 1)
  const step = Math.ceil(pct * 10) // 1..10
  const lightness = 97 - step * 5  // 92, 87, 82, ... 47
  const saturation = 50 + step * 5  // 55, 60, 65, ... 100
  return {
    color: `hsl(0, ${saturation}%, ${Math.max(lightness - 20, 20)}%)`,
    background: `hsl(0, ${saturation}%, ${lightness}%)`,
    fontWeight: step >= 3 ? 700 : undefined,
    borderRadius: '4px',
  }
}

function statusLabel(state: ReadyResponse['state'] | undefined): string {
  if (state === 'RUNNING') {
    return 'Running'
  }
  if (state === 'PREPARING') {
    return 'Preparing'
  }
  if (state === 'STOPPING') {
    return 'Stopping'
  }
  if (state === 'IDLE') {
    return 'Idle'
  }
  return 'Offline'
}

function statusToneClass(state: ReadyResponse['state'] | undefined): string {
  if (state === 'RUNNING') {
    return 'pill--state-running'
  }
  if (state === 'IDLE') {
    return 'pill--state-idle'
  }
  if (state === undefined) {
    return 'pill--state-offline'
  }
  return 'pill--state-idle'
}

function normalizedString(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function metricSortByName(a: { name: string }, b: { name: string }): number {
  return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' })
}

function latestMetricEventData(metric: MetricsResponse['metrics'][number]): Record<string, unknown> | null {
  const latestEvent = metric.events && metric.events.length > 0 ? metric.events[metric.events.length - 1] : null
  const rawData = latestEvent?.data
  if (!rawData || typeof rawData !== 'object') {
    return null
  }
  return rawData
}

function metricKind(metric: MetricsResponse['metrics'][number]): string | null {
  const data = latestMetricEventData(metric)
  return normalizedString(data?.source) ?? null
}

function metricSource(metric: MetricsResponse['metrics'][number]): string {
  return metricKind(metric) ?? 'unknown'
}

function sortCountRows(values: Record<string, number>): Array<{ label: string; count: number }> {
  return Object.entries(values)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], undefined, { sensitivity: 'base' }))
    .map(([label, count]) => ({ label, count }))
}

function mergeCountMap(target: Record<string, number>, source: Record<string, number>): void {
  for (const [label, count] of Object.entries(source)) {
    if (!Number.isFinite(count) || count <= 0) {
      continue
    }
    target[label] = (target[label] ?? 0) + count
  }
}

function parseStreamEventTimestampMs(eventId: string): number | null {
  const rawTimestamp = eventId.split('-', 1)[0]
  const parsed = Number.parseInt(rawTimestamp, 10)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null
  }
  return parsed
}

function formatEventTimestamp(value: number | null): string {
  if (value === null) {
    return '—'
  }
  return new Date(value).toLocaleString('en-US', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function readErrorTraceback(data: Record<string, unknown>): string | null {
  const tracebackFields = [
    'traceback',
    'stacktrace',
    'stack_trace',
    'exception_traceback',
    'error_traceback',
  ] as const

  for (const field of tracebackFields) {
    const raw = data[field]
    if (typeof raw !== 'string') {
      continue
    }
    const value = raw.trim()
    if (value.length > 0) {
      return value
    }
  }
  return null
}

function toStatsRows(
  metrics: MetricsResponse | null,
  scope: StatsScope,
  rps1sByMetric: Record<string, number>,
): StatsRow[] {
  if (!metrics) {
    return []
  }

  type RowWithMeta = StatsRow & {
    metricId: string
    kind: string | null
    stepName: string | null
    isStepMetric: boolean
  }

  const rows: RowWithMeta[] = metrics.metrics.map((item) => {
    const aggregate = scope === 'total' ? item.aggregate_total : item.aggregate
    const failure = aggregate.errors
    const success = Math.max(0, aggregate.requests - failure)
    const kind = metricKind(item)

    // metric_id is "step_name/call_name" for nested metrics, plain name for steps
    const slashIdx = item.metric_id.indexOf('/')
    const hasStepPrefix = slashIdx > 0
    const stepName = hasStepPrefix
      ? item.metric_id.slice(0, slashIdx)
      : (kind === 'step' ? item.metric_id : null)
    const displayName = hasStepPrefix
      ? item.metric_id.slice(slashIdx + 1)
      : item.metric_id
    const isStepMetric = kind === 'step' && !hasStepPrefix

    return {
      metricId: item.metric_id,
      name: displayName,
      success,
      failure,
      medianMs: aggregate.latency_median_ms,
      p95Ms: aggregate.latency_p95_ms,
      p99Ms: aggregate.latency_p99_ms,
      averageMs: aggregate.latency_avg_ms,
      rps: rps1sByMetric[item.metric_id] ?? 0,
      failureRate: aggregate.error_rate,
      kind,
      stepName,
      isStepMetric,
    }
  })

  const topLevelRows: RowWithMeta[] = []
  const stepRowsByName = new Map<string, RowWithMeta>()
  const httpRowsByStep = new Map<string, RowWithMeta[]>()

  for (const row of rows) {
    if (row.isStepMetric) {
      stepRowsByName.set(row.metricId, row)
      continue
    }

    if (!row.isStepMetric && row.stepName !== null && row.stepName !== '__unknown__') {
      const grouped = httpRowsByStep.get(row.stepName) ?? []
      grouped.push(row)
      httpRowsByStep.set(row.stepName, grouped)
      continue
    }

    topLevelRows.push(row)
  }

  for (const stepRow of stepRowsByName.values()) {
    topLevelRows.push(stepRow)
  }

  for (const [stepName, childRows] of httpRowsByStep.entries()) {
    if (stepRowsByName.has(stepName)) {
      continue
    }
    // Create a synthetic step row that aggregates all children
    const syntheticRow: RowWithMeta = {
      metricId: stepName,
      name: stepName,
      success: childRows.reduce((s, r) => s + r.success, 0),
      failure: childRows.reduce((s, r) => s + r.failure, 0),
      medianMs: null,
      p95Ms: null,
      p99Ms: null,
      averageMs: null,
      rps: childRows.reduce((s, r) => s + r.rps, 0),
      failureRate: 0,
      kind: 'synthetic',
      stepName,
      isStepMetric: true,
      isNested: false,
    }
    const total = syntheticRow.success + syntheticRow.failure
    syntheticRow.failureRate = total > 0 ? syntheticRow.failure / total : 0
    stepRowsByName.set(stepName, syntheticRow)
    topLevelRows.push(syntheticRow)
  }

  topLevelRows.sort(metricSortByName)

  const output: StatsRow[] = []
  for (const row of topLevelRows) {
    const children = row.isStepMetric ? [...(httpRowsByStep.get(row.metricId) ?? [])] : []
    children.sort(metricSortByName)
    output.push({ ...row, isNested: false, hasChildren: children.length > 0 })
    for (const child of children) {
      output.push({ ...child, isNested: true, parentName: row.name })
    }
  }

  return output
}

function formatChartTime(ts: number): string {
  const date = new Date(ts * 1000)
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function roundTo(value: number, digits = 1): number {
  return Number(value.toFixed(digits))
}

function resolveWorkerActiveUsersCount(worker: WorkersResponse['workers'][number]): number {
  return Math.max(0, Math.floor(worker.active_users_count))
}

function sumUsersForActiveWorkers(
  workers: WorkersResponse,
  activeWorkerIds: readonly string[] | null,
): number {
  if (!activeWorkerIds) {
    return 0
  }
  const activeSet = new Set(activeWorkerIds)
  return workers.workers.reduce((total, worker) => {
    if (!activeSet.has(worker.worker_id)) {
      return total
    }
    return total + resolveWorkerActiveUsersCount(worker)
  }, 0)
}

function buildHistoryPoint(
  metrics: MetricsResponse,
  workers: WorkersResponse,
  activeWorkerIds: readonly string[] | null,
  generatedAt: number,
  rpsByMetric: Record<string, number>,
): ChartHistoryPoint {
  const totalUsers =
    activeWorkerIds === null ? null : sumUsersForActiveWorkers(workers, activeWorkerIds)
  const latencyByMetric: Record<string, Record<LatencySeriesId, number | null>> = {}
  for (const metric of metrics.metrics) {
    const metricId = metric.metric_id
    latencyByMetric[metricId] = {
      averageMs: metric.aggregate.latency_avg_ms,
      medianMs: metric.aggregate.latency_median_ms,
      p95Ms: metric.aggregate.latency_p95_ms,
      p99Ms: metric.aggregate.latency_p99_ms,
    }
  }

  return {
    ts: generatedAt,
    totalUsers,
    rpsByMetric,
    latencyByMetric,
  }
}

function mapServerHistoryPoint(
  point: MetricsHistoryResponse['points'][number],
): ChartHistoryPoint {
  const rpsByMetric: Record<string, number> = {}
  const latencyByMetric: Record<string, Record<LatencySeriesId, number | null>> = {}

  for (const [metricId, metricValues] of Object.entries(point.metrics)) {
    rpsByMetric[metricId] = metricValues.rps
    latencyByMetric[metricId] = {
      averageMs: metricValues.latency_avg_ms,
      medianMs: metricValues.latency_median_ms,
      p95Ms: metricValues.latency_p95_ms,
      p99Ms: metricValues.latency_p99_ms,
    }
  }

  return {
    ts: point.ts,
    totalUsers: point.users,
    rpsByMetric,
    latencyByMetric,
  }
}

function parseInputValue(rawValue: string): unknown {
  const value = rawValue.trim()
  if (value.length === 0) {
    return ''
  }

  if (value === 'true') {
    return true
  }

  if (value === 'false') {
    return false
  }

  if (/^-?\d+(\.\d+)?$/.test(value)) {
    return Number(value)
  }

  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

function formatLastSeen(ageSeconds: number | null): string {
  if (ageSeconds === null) {
    return '—'
  }
  if (ageSeconds < 60) {
    return `${ageSeconds}s ago`
  }
  if (ageSeconds < 3600) {
    return `${Math.floor(ageSeconds / 60)}m ago`
  }
  if (ageSeconds < 86_400) {
    return `${Math.floor(ageSeconds / 3600)}h ago`
  }
  return `${Math.floor(ageSeconds / 86_400)}d ago`
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value))
}

function formatRamUsage(processRamBytes: number | null, totalRamBytes: number | null): string | null {
  if (processRamBytes === null && totalRamBytes === null) {
    return null
  }

  const processLabel =
    processRamBytes === null
      ? '—'
      : `${numberFormatter.format(Math.round(processRamBytes / BYTES_IN_MB))} Mb`
  const totalLabel =
    totalRamBytes === null
      ? '—'
      : `${gigabytesFormatter.format(totalRamBytes / BYTES_IN_GB)} Gb`

  return `${processLabel} / ${totalLabel}`
}

function loadTone(value: number | null): 'ok' | 'warn' | 'critical' {
  if (value === null) {
    return 'ok'
  }
  if (value >= 85) {
    return 'critical'
  }
  if (value >= 65) {
    return 'warn'
  }
  return 'ok'
}

function workerBadge(
  worker: WorkersResponse['workers'][number],
): { label: 'Healthy' | 'Degraded' | 'Failing'; tone: 'healthy' | 'degraded' | 'failing' } {
  if (worker.status === 'healthy') {
    return { label: 'Healthy', tone: 'healthy' }
  }

  if (worker.status === 'unhealthy' || (worker.heartbeat_age_s ?? 0) > 30) {
    return { label: 'Failing', tone: 'failing' }
  }

  return { label: 'Degraded', tone: 'degraded' }
}

function useDashboardData(metricsEventsCount: number) {
  const [ready, setReady] = useState<ReadyResponse | null>(null)
  const [workers, setWorkers] = useState<WorkersResponse | null>(null)
  const [resources, setResources] = useState<ResourcesResponse | null>(null)
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [rps1sByMetric, setRps1sByMetric] = useState<Record<string, number>>({})
  const [history, setHistory] = useState<ChartHistoryPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)
  const previousTotalsRef = useRef<Map<string, { requests: number; tsMs: number }>>(new Map())
  const lastEpochRef = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    if (inFlightRef.current) {
      return
    }

    inFlightRef.current = true
    setRefreshing(true)

    const [readyResult, workersResult, resourcesResult, metricsResult] = await Promise.allSettled([
      fetchReady(),
      fetchWorkers(),
      fetchResources(),
      fetchMetrics({
        count: metricsEventsCount,
        includeEvents: true,
      }),
    ])

    const errors: string[] = []
    const pushError = (scope: string, reason: unknown) => {
      const message = reason instanceof Error ? reason.message : 'request failed'
      errors.push(`${scope}: ${message}`)
    }

    if (readyResult.status === 'fulfilled') {
      setReady(readyResult.value)
      const currentEpoch = readyResult.value.epoch
      if (lastEpochRef.current === null) {
        lastEpochRef.current = currentEpoch
      } else if (lastEpochRef.current !== currentEpoch) {
        lastEpochRef.current = currentEpoch
        previousTotalsRef.current.clear()
        setRps1sByMetric({})
        setHistory([])
      }
    } else {
      setReady(null)
      pushError('ready', readyResult.reason)
    }

    if (workersResult.status === 'fulfilled') {
      setWorkers(workersResult.value)
    } else {
      pushError('workers', workersResult.reason)
    }

    if (resourcesResult.status === 'fulfilled') {
      setResources(resourcesResult.value)
    } else {
      pushError('resources', resourcesResult.reason)
    }

    let nextRpsByMetricForHistory: Record<string, number> | null = null

    if (metricsResult.status === 'fulfilled') {
      setMetrics(metricsResult.value)
      const nowMs = Date.now()
      const previousTotals = previousTotalsRef.current
      const nextTotals = new Map<string, { requests: number; tsMs: number }>()
      const nextRpsByMetric: Record<string, number> = {}

      for (const metric of metricsResult.value.metrics) {
        const metricId = metric.metric_id
        const totalRequests = metric.aggregate_total.requests
        const previous = previousTotals.get(metricId)
        let rps = 0

        if (previous) {
          const deltaRequests = totalRequests - previous.requests
          const deltaSeconds = (nowMs - previous.tsMs) / 1000
          if (deltaRequests >= 0 && deltaSeconds > 0) {
            rps = deltaRequests / deltaSeconds
          }
        }

        nextRpsByMetric[metricId] = roundTo(Math.max(0, rps))
        nextTotals.set(metricId, { requests: totalRequests, tsMs: nowMs })
      }

      previousTotalsRef.current = nextTotals
      setRps1sByMetric(nextRpsByMetric)
      nextRpsByMetricForHistory = nextRpsByMetric
    } else {
      pushError('metrics', metricsResult.reason)
    }

    const shouldAppendHistory =
      readyResult.status === 'fulfilled' &&
      (readyResult.value.state === 'PREPARING' ||
        readyResult.value.state === 'RUNNING' ||
        readyResult.value.state === 'STOPPING')

    if (shouldAppendHistory && metricsResult.status === 'fulfilled' && workersResult.status === 'fulfilled') {
      const ts =
        metricsResult.value.generated_at > 0
          ? metricsResult.value.generated_at
          : Math.floor(Date.now() / 1000)
      const activeWorkerIds = readyResult.status === 'fulfilled' ? readyResult.value.workers : null
      const point = buildHistoryPoint(
        metricsResult.value,
        workersResult.value,
        activeWorkerIds,
        ts,
        nextRpsByMetricForHistory ?? {},
      )
      setHistory((current) => {
        const merged =
          current.length > 0 && current[current.length - 1].ts === point.ts
            ? [...current.slice(0, -1), point]
            : [...current, point]
        return merged
      })
    }

    setError(errors.length > 0 ? Array.from(new Set(errors)).join(' | ') : null)
    setLoading(false)
    setRefreshing(false)
    inFlightRef.current = false
  }, [metricsEventsCount])

  useEffect(() => {
    const initialTimerId = window.setTimeout(() => {
      void refresh()
    }, 0)
    const timerId = window.setInterval(() => {
      void refresh()
    }, REFRESH_INTERVAL_MS)

    return () => {
      window.clearTimeout(initialTimerId)
      window.clearInterval(timerId)
    }
  }, [refresh])

  return {
    ready,
    workers,
    resources,
    metrics,
    rps1sByMetric,
    history,
    loading,
    refreshing,
    error,
    refresh,
  }
}

function TracebackBlock({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)
  const ref = useRef<HTMLPreElement>(null)
  const [overflows, setOverflows] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (el) setOverflows(el.scrollHeight > el.clientHeight + 2)
  }, [content])

  return (
    <div>
      <pre
        ref={ref}
        className={
          'errors-traceback-content' + (expanded ? ' errors-traceback-content--expanded' : '')
        }
      >
        {content}
      </pre>
      {(overflows || expanded) && (
        <button
          type="button"
          className="errors-traceback-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? 'Collapse' : 'Expand'}
        </button>
      )}
    </div>
  )
}

export function LoadTestingScreen() {
  const [activeTab, setActiveTab] = useState<TabId>('statistics')
  const [statsScope, setStatsScope] = useState<StatsScope>('total')
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [visibleColumns, setVisibleColumns] = useState<StatsColumnId[]>(defaultVisibleColumns)
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [errorsCategoryOpen, setErrorsCategoryOpen] = useState(false)

  const [startModalOpen, setStartModalOpen] = useState(false)
  const [changeUsersModalOpen, setChangeUsersModalOpen] = useState(false)
  const [resourceModalOpen, setResourceModalOpen] = useState(false)
  const [resourceViewModalOpen, setResourceViewModalOpen] = useState(false)
  const [resourceViewName, setResourceViewName] = useState('')

  const [stopping, setStopping] = useState(false)
  const [starting, setStarting] = useState(false)
  const [changingUsers, setChangingUsers] = useState(false)
  const [creatingResource, setCreatingResource] = useState(false)

  const [notifications, setNotifications] = useState<NotificationItem[]>([])

  const [targetUsersInput, setTargetUsersInput] = useState('1000')
  const [changeUsersInput, setChangeUsersInput] = useState('0')
  const [resourceNameInput, setResourceNameInput] = useState('')
  const [resourceCountInput, setResourceCountInput] = useState('1')
  const [selectedRpsMetrics, setSelectedRpsMetrics] = useState<string[]>([])
  const [rpsSelectionTouched, setRpsSelectionTouched] = useState(false)
  const [selectedLatencyMetrics, setSelectedLatencyMetrics] = useState<string[]>([])
  const [latencySelectionTouched, setLatencySelectionTouched] = useState(false)
  const [selectedLatencyType, setSelectedLatencyType] = useState<LatencySeriesId>('p95Ms')
  const [selectedChartRange, setSelectedChartRange] = useState<ChartRangeId>('all')
  const [showUsersOnRpsChart, setShowUsersOnRpsChart] = useState(true)
  const [serverChartHistory, setServerChartHistory] = useState<ChartHistoryPoint[]>([])
  const [loadingServerChartHistory, setLoadingServerChartHistory] = useState(false)
  const [chartEpoch, setChartEpoch] = useState<number | null>(null)
  const [rpsMetricsOpen, setRpsMetricsOpen] = useState(false)
  const [rpsUsersOpen, setRpsUsersOpen] = useState(false)
  const [rpsRangeOpen, setRpsRangeOpen] = useState(false)
  const [latencyMetricsOpen, setLatencyMetricsOpen] = useState(false)
  const [latencyTypeOpen, setLatencyTypeOpen] = useState(false)

  const [scenarioSpec, setScenarioSpec] = useState<ScenarioOnInitSpec | null>(null)
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioError, setScenarioError] = useState<string | null>(null)
  const [initParamValues, setInitParamValues] = useState<Record<string, string>>({})
  const [selectedTracebackCategory, setSelectedTracebackCategory] = useState('all')

  const columnsContainerRef = useRef<HTMLDivElement | null>(null)
  const sourcesContainerRef = useRef<HTMLDivElement | null>(null)
  const errorsCategoryContainerRef = useRef<HTMLDivElement | null>(null)
  const rpsMetricsContainerRef = useRef<HTMLDivElement | null>(null)
  const rpsUsersContainerRef = useRef<HTMLDivElement | null>(null)
  const rpsRangeContainerRef = useRef<HTMLDivElement | null>(null)
  const latencyMetricsContainerRef = useRef<HTMLDivElement | null>(null)
  const latencyTypeContainerRef = useRef<HTMLDivElement | null>(null)
  const notificationIdRef = useRef(0)
  const notificationTimersRef = useRef<Map<number, number>>(new Map())
  const lastFetchErrorRef = useRef<string | null>(null)
  const lastServerHistoryTsRef = useRef<number | null>(null)
  const metricsEventsCount = activeTab === 'errors' ? ERROR_EVENTS_FETCH_COUNT : 1

  const {
    ready,
    workers,
    resources,
    metrics,
    rps1sByMetric,
    history,
    error,
    refresh,
  } = useDashboardData(metricsEventsCount)

  const testStartedAtRef = useRef<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState<number | null>(null)

  useEffect(() => {
    if (ready?.state === 'RUNNING') {
      if (testStartedAtRef.current === null) {
        testStartedAtRef.current = Date.now()
      }
    } else {
      testStartedAtRef.current = null
      setElapsedSeconds(null)
    }
  }, [ready?.state])

  useEffect(() => {
    if (testStartedAtRef.current === null) return
    const tick = () => {
      if (testStartedAtRef.current !== null) {
        setElapsedSeconds(Math.floor((Date.now() - testStartedAtRef.current) / 1000))
      }
    }
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [ready?.state])

  const dismissNotification = useCallback((id: number) => {
    const timerId = notificationTimersRef.current.get(id)
    if (timerId !== undefined) {
      window.clearTimeout(timerId)
      notificationTimersRef.current.delete(id)
    }
    setNotifications((current) => current.filter((item) => item.id !== id))
  }, [])

  const pushNotification = useCallback(
    (tone: NotificationTone, message: string) => {
      const normalizedMessage = message.trim()
      if (!normalizedMessage) {
        return
      }

      const id = notificationIdRef.current + 1
      notificationIdRef.current = id
      setNotifications((current) => [...current, { id, tone, message: normalizedMessage }].slice(-5))

      const ttl = tone === 'error' ? ERROR_NOTIFICATION_TTL_MS : NOTIFICATION_TTL_MS
      const timerId = window.setTimeout(() => {
        dismissNotification(id)
      }, ttl)
      notificationTimersRef.current.set(id, timerId)
    },
    [dismissNotification],
  )

  const rows = useMemo(
    () => toStatsRows(metrics, statsScope, rps1sByMetric),
    [metrics, rps1sByMetric, statsScope],
  )

  const availableSources = useMemo(() => {
    if (!metrics) {
      return []
    }
    const sourceSet = new Set<string>()
    for (const metric of metrics.metrics) {
      sourceSet.add(metricSource(metric))
    }
    return Array.from(sourceSet).sort((a, b) => a.localeCompare(b))
  }, [metrics])

  const totalUsers = useMemo(() => {
    if (!workers || !ready) {
      return 0
    }
    return sumUsersForActiveWorkers(workers, ready.workers)
  }, [ready, workers])

  const totalRps = useMemo(() => {
    if (!metrics) {
      return 0
    }
    return metrics.metrics.reduce((total, metric) => {
      if (metricKind(metric) === 'step') {
        return total
      }
      return total + (rps1sByMetric[metric.metric_id] ?? 0)
    }, 0)
  }, [metrics, rps1sByMetric])

  const errorBreakdown = useMemo<ErrorBreakdownSnapshot>(() => {
    const empty: ErrorBreakdownSnapshot = {
      totalRequests: 0,
      totalErrors: 0,
      totalFatal: 0,
      resultCodeRows: [],
      resultCategoryRows: [],
      sourceRows: [],
    }
    if (!metrics) {
      return empty
    }

    const activeSourceSet = new Set(
      selectedSources.length > 0 ? selectedSources : availableSources,
    )
    const resultCodeCounts: Record<string, number> = {}
    const resultCategoryCounts: Record<string, number> = {}
    const sourceTotals = new Map<string, SourceBreakdownRow>()
    let totalRequests = 0
    let totalErrors = 0
    let totalFatal = 0

    for (const metric of metrics.metrics) {
      const source = metricSource(metric)
      if (activeSourceSet.size > 0 && !activeSourceSet.has(source)) {
        continue
      }

      const aggregate = statsScope === 'total' ? metric.aggregate_total : metric.aggregate
      totalRequests += aggregate.requests
      totalErrors += aggregate.errors
      totalFatal += aggregate.fatal_count
      mergeCountMap(resultCodeCounts, aggregate.result_code_counts)
      mergeCountMap(resultCategoryCounts, aggregate.result_category_counts)

      const currentSource = sourceTotals.get(source) ?? {
        source,
        requests: 0,
        errors: 0,
        fatal: 0,
      }
      currentSource.requests += aggregate.requests
      currentSource.errors += aggregate.errors
      currentSource.fatal += aggregate.fatal_count
      sourceTotals.set(source, currentSource)
    }

    const sourceRows = Array.from(sourceTotals.values()).sort(
      (a, b) => b.errors - a.errors || a.source.localeCompare(b.source),
    )
    return {
      totalRequests,
      totalErrors,
      totalFatal,
      resultCodeRows: sortCountRows(resultCodeCounts),
      resultCategoryRows: sortCountRows(resultCategoryCounts),
      sourceRows,
    }
  }, [availableSources, metrics, selectedSources, statsScope])

  const tracebackRows = useMemo<TracebackRow[]>(() => {
    if (!metrics) {
      return []
    }

    const rows: TracebackRow[] = []

    for (const metric of metrics.metrics) {
      if (!metric.events) {
        continue
      }

      for (const event of metric.events) {
        if (!event.data || typeof event.data !== 'object') {
          continue
        }

        const data = event.data as Record<string, unknown>
        const category = normalizedString(data.result_category) ?? 'unknown'
        const errorMessage = normalizedString(data.error_message)
        const traceback = readErrorTraceback(data)
        const status = typeof data.status === 'boolean' ? data.status : null
        const isErrorEvent =
          status === false || category !== 'ok' || traceback !== null || errorMessage !== null

        if (!isErrorEvent) {
          continue
        }

        const detail = traceback ?? errorMessage
        if (detail === null) {
          continue
        }

        const source = normalizedString(data.source) ?? 'unknown'
        const stage = normalizedString(data.stage) ?? 'unknown'
        const errorType = normalizedString(data.error_type)
        const timestampMs = parseStreamEventTimestampMs(event.event_id)

        rows.push({
          key: `${metric.metric_id}:${event.event_id}`,
          metricId: normalizedString(data.name) ?? metric.metric_id,
          source,
          stage,
          category,
          errorType,
          errorMessage,
          traceback: detail,
          eventId: event.event_id,
          timestampMs,
        })
      }
    }

    return rows.sort((a, b) => {
      if (a.timestampMs !== null && b.timestampMs !== null) {
        return b.timestampMs - a.timestampMs
      }
      if (a.timestampMs !== null) {
        return -1
      }
      if (b.timestampMs !== null) {
        return 1
      }
      return b.eventId.localeCompare(a.eventId)
    })
  }, [metrics])

  const tracebackCategories = useMemo(() => {
    const values = new Set<string>()
    for (const row of tracebackRows) {
      values.add(row.category)
    }
    return Array.from(values).sort((a, b) => a.localeCompare(b))
  }, [tracebackRows])

  const filteredTracebackRows = useMemo(() => {
    if (selectedTracebackCategory === 'all') {
      return tracebackRows
    }
    return tracebackRows.filter((row) => row.category === selectedTracebackCategory)
  }, [selectedTracebackCategory, tracebackRows])

  const selectedSourcesSummary = useMemo(() => {
    if (availableSources.length === 0) {
      return 'All sources'
    }
    if (selectedSources.length === availableSources.length) {
      return 'All sources'
    }
    if (selectedSources.length === 1) {
      return selectedSources[0]
    }
    return `${selectedSources.length} selected`
  }, [availableSources, selectedSources])

  const selectedErrorsCategoryLabel =
    selectedTracebackCategory === 'all' ? 'All categories' : selectedTracebackCategory

  useEffect(() => {
    const currentStatus = statusLabel(ready?.state)
    document.title = `Vikhry - ${currentStatus}`
  }, [ready?.state])

  const workerRows = useMemo(() => {
    if (!workers) {
      return []
    }

    return workers.workers.map((worker) => {
      const badge = workerBadge(worker)
      const activeUsers = resolveWorkerActiveUsersCount(worker)
      const totalAssignedUsers = Math.max(0, Math.floor(worker.users_count))
      const usersSummary = `${numberFormatter.format(activeUsers)}/${numberFormatter.format(totalAssignedUsers)}`
      const processRamBytes = worker.process_ram_bytes
      const totalRamBytes = worker.total_ram_bytes
      const ramUsage = formatRamUsage(processRamBytes, totalRamBytes)

      const rawCpu = worker.cpu_percent
      const cpuLoad =
        typeof rawCpu === 'number' && Number.isFinite(rawCpu)
          ? clampPercent(rawCpu)
          : null

      const rawMemory = (() => {
        if (processRamBytes === null || totalRamBytes === null || totalRamBytes <= 0) {
          return null
        }
        return (processRamBytes / totalRamBytes) * 100
      })()
      const ramLoad =
        typeof rawMemory === 'number' && Number.isFinite(rawMemory)
          ? clampPercent(rawMemory)
          : null

      return {
        worker,
        badge,
        usersSummary,
        cpuLoad,
        ramLoad,
        ramUsage,
      }
    })
  }, [workers])

  const chartHistory = useMemo(() => {
    const pointsByTs = new Map<number, ChartHistoryPoint>()

    for (const point of serverChartHistory) {
      pointsByTs.set(point.ts, {
        ts: point.ts,
        totalUsers: point.totalUsers,
        rpsByMetric: { ...point.rpsByMetric },
        latencyByMetric: { ...point.latencyByMetric },
      })
    }

    for (const point of history) {
      const existing = pointsByTs.get(point.ts)
      if (!existing) {
        pointsByTs.set(point.ts, {
          ts: point.ts,
          totalUsers: point.totalUsers,
          rpsByMetric: { ...point.rpsByMetric },
          latencyByMetric: { ...point.latencyByMetric },
        })
        continue
      }

      pointsByTs.set(point.ts, {
        ts: point.ts,
        totalUsers: point.totalUsers ?? existing.totalUsers,
        rpsByMetric: existing.rpsByMetric,
        latencyByMetric: existing.latencyByMetric,
      })
    }

    return Array.from(pointsByTs.values()).sort((a, b) => a.ts - b.ts)
  }, [history, serverChartHistory])

  const availableMetricOptions = useMemo<ChartMetricOption[]>(() => {
    const optionsById = new Map<string, ChartMetricOption>()
    if (metrics) {
      for (const metric of metrics.metrics) {
        optionsById.set(metric.metric_id, {
          id: metric.metric_id,
          source: metricKind(metric) ?? 'unknown',
        })
      }
    }
    for (const point of chartHistory) {
      for (const metricId of Object.keys(point.rpsByMetric)) {
        if (!optionsById.has(metricId)) {
          optionsById.set(metricId, { id: metricId, source: 'unknown' })
        }
      }
    }

    const sourceWeight = (source: string): number => {
      if (source === 'step') {
        return 0
      }
      if (source === 'http') {
        return 1
      }
      return 2
    }

    return Array.from(optionsById.values()).sort(
      (a, b) =>
        sourceWeight(a.source) - sourceWeight(b.source) ||
        a.id.localeCompare(b.id, undefined, { numeric: true, sensitivity: 'base' }),
    )
  }, [chartHistory, metrics])

  const availableMetricIds = useMemo(
    () => availableMetricOptions.map((option) => option.id),
    [availableMetricOptions],
  )

  const visibleHistory = useMemo(() => {
    if (chartHistory.length === 0 || selectedChartRange === 'all') {
      return chartHistory
    }
    const rangeWindowS = chartRangeToSeconds[selectedChartRange]
    const lastTs = chartHistory[chartHistory.length - 1].ts
    const minTs = lastTs - rangeWindowS
    return chartHistory.filter((point) => point.ts >= minTs)
  }, [chartHistory, selectedChartRange])

  const rpsChartData = useMemo(() => {
    if (visibleHistory.length === 0 || (selectedRpsMetrics.length === 0 && !showUsersOnRpsChart)) {
      return []
    }

    let previousUsers: number | null = null
    return visibleHistory.map((point) => {
      const currentUsers = point.totalUsers
      const usersChanged =
        currentUsers !== null && previousUsers !== null && previousUsers !== currentUsers
      if (currentUsers !== null) {
        previousUsers = currentUsers
      }
      const usersForRow = previousUsers
      const row: Record<string, number | string | null> = {
        tsMs: point.ts * 1000,
        time: formatChartTime(point.ts),
        __users: usersForRow,
        __usersChangeMarker: usersChanged ? usersForRow : null,
      }
      for (const metricId of selectedRpsMetrics) {
        row[metricId] = point.rpsByMetric[metricId] ?? null
      }
      return row
    })
  }, [selectedRpsMetrics, showUsersOnRpsChart, visibleHistory])

  const latencyChartData = useMemo(() => {
    if (visibleHistory.length === 0 || selectedLatencyMetrics.length === 0) {
      return []
    }
    return visibleHistory.map((point) => {
      const row: Record<string, number | string | null> = {
        tsMs: point.ts * 1000,
        time: formatChartTime(point.ts),
      }
      for (const metricId of selectedLatencyMetrics) {
        row[metricId] = point.latencyByMetric[metricId]?.[selectedLatencyType] ?? null
      }
      return row
    })
  }, [selectedLatencyMetrics, selectedLatencyType, visibleHistory])

  const selectedChartRangeLabel = useMemo(() => {
    return chartRanges.find((option) => option.id === selectedChartRange)?.label ?? 'All time'
  }, [selectedChartRange])

  const selectedLatencyLabel = useMemo(() => {
    return latencySeriesMeta.find((item) => item.id === selectedLatencyType)?.label ?? 'P95'
  }, [selectedLatencyType])

  const selectedRpsMetricsSummary = useMemo(() => {
    if (availableMetricOptions.length === 0) {
      return 'Metrics'
    }
    if (selectedRpsMetrics.length === 0) {
      return 'No metrics'
    }
    if (selectedRpsMetrics.length === 1) {
      return selectedRpsMetrics[0]
    }
    return `${selectedRpsMetrics.length} metrics`
  }, [availableMetricOptions.length, selectedRpsMetrics])

  const selectedLatencyMetricsSummary = useMemo(() => {
    if (availableMetricOptions.length === 0) {
      return 'Metrics'
    }
    if (selectedLatencyMetrics.length === 0) {
      return 'No metrics'
    }
    if (selectedLatencyMetrics.length === 1) {
      return selectedLatencyMetrics[0]
    }
    return `${selectedLatencyMetrics.length} metrics`
  }, [availableMetricOptions.length, selectedLatencyMetrics])

  const canStop = ready?.state === 'RUNNING' || ready?.state === 'PREPARING'
  const canStart = ready?.state === 'IDLE'
  const canChangeUsers = ready?.state === 'RUNNING'
  const resourceNames = useMemo(
    () => (resources?.resources ?? []).map((resource) => resource.resource_name),
    [resources],
  )
  const resourceCounts = useMemo(() => {
    const map: Record<string, number> = {}
    for (const r of resources?.resources ?? []) {
      map[r.resource_name] = r.count
    }
    return map
  }, [resources])
  const selectedResourceName = useMemo(() => {
    if (resourceNames.includes(resourceNameInput)) {
      return resourceNameInput
    }
    return resourceNames[0] ?? ''
  }, [resourceNameInput, resourceNames])
  const openChangeUsersModal = useCallback(() => {
    setChangeUsersInput(String(totalUsers))
    setChangeUsersModalOpen(true)
  }, [totalUsers])

  const openResourceModal = useCallback(
    (resourceName?: string) => {
      const nextName = (() => {
        if (resourceName && resourceNames.includes(resourceName)) {
          return resourceName
        }
        if (resourceNameInput && resourceNames.includes(resourceNameInput)) {
          return resourceNameInput
        }
        return resourceNames[0] ?? ''
      })()

      setResourceNameInput(nextName)
      setResourceCountInput('1')
      setResourceModalOpen(true)
    },
    [resourceNameInput, resourceNames],
  )

  const onStop = useCallback(async () => {
    try {
      setStopping(true)
      await stopTest()
      pushNotification('success', 'Stop command sent.')
      await refresh()
    } catch (stopError) {
      pushNotification('error', stopError instanceof Error ? stopError.message : 'Failed to stop test')
    } finally {
      setStopping(false)
    }
  }, [pushNotification, refresh])

  const onStart = useCallback(async () => {
    const targetUsers = Number(targetUsersInput)
    if (!Number.isInteger(targetUsers) || targetUsers < 0) {
      pushNotification('error', 'Users must be an integer >= 0.')
      return
    }

    const initParams: Record<string, unknown> = {}
    if (scenarioSpec) {
      for (const param of scenarioSpec.params) {
        const rawValue = initParamValues[param.name]?.trim() ?? ''
        if (rawValue.length === 0) {
          if (param.required) {
            pushNotification('error', `Init parameter \`${param.name}\` is required.`)
            return
          }
          continue
        }
        initParams[param.name] = parseInputValue(rawValue)
      }
    }

    try {
      setStarting(true)
      await startTest({
        target_users: targetUsers,
        init_params: initParams,
      })
      setStartModalOpen(false)
      pushNotification('success', 'Start command sent.')
      await refresh()
    } catch (startError) {
      pushNotification('error', startError instanceof Error ? startError.message : 'Failed to start test')
    } finally {
      setStarting(false)
    }
  }, [initParamValues, pushNotification, refresh, scenarioSpec, targetUsersInput])

  const onChangeUsers = useCallback(async () => {
    const targetUsers = Number(changeUsersInput)
    if (!Number.isInteger(targetUsers) || targetUsers < 0) {
      pushNotification('error', 'Users must be an integer >= 0.')
      return
    }

    try {
      setChangingUsers(true)
      await changeUsers({ target_users: targetUsers })
      setChangeUsersModalOpen(false)
      pushNotification('success', 'Users change command sent.')
      await refresh()
    } catch (changeError) {
      pushNotification(
        'error',
        changeError instanceof Error ? changeError.message : 'Failed to change users',
      )
    } finally {
      setChangingUsers(false)
    }
  }, [changeUsersInput, pushNotification, refresh])

  const onCreateResource = useCallback(async () => {
    const name = selectedResourceName.trim()
    const count = Number(resourceCountInput)

    if (!name) {
      pushNotification('error', 'Resource name is required.')
      return
    }

    if (!Number.isInteger(count) || count < 1) {
      pushNotification('error', 'Resource count must be an integer >= 1.')
      return
    }

    try {
      setCreatingResource(true)
      await createResource({ name, count })
      setResourceModalOpen(false)
      pushNotification('success', `Created ${count} resource(s) for ${name}.`)
      await refresh()
    } catch (createError) {
      pushNotification(
        'error',
        createError instanceof Error ? createError.message : 'Failed to create resources',
      )
    } finally {
      setCreatingResource(false)
    }
  }, [pushNotification, refresh, resourceCountInput, selectedResourceName])

  const toggleColumn = useCallback((columnId: StatsColumnId) => {
    setVisibleColumns((current) => {
      const meta = statsColumns.find((column) => column.id === columnId)
      if (meta?.required) {
        return current
      }
      if (current.includes(columnId)) {
        return current.filter((item) => item !== columnId)
      }
      return [...current, columnId]
    })
  }, [])

  const toggleColumnsMenu = useCallback(() => {
    setColumnsOpen((current) => !current)
    setSourcesOpen(false)
    setErrorsCategoryOpen(false)
    setRpsMetricsOpen(false)
    setRpsUsersOpen(false)
    setRpsRangeOpen(false)
    setLatencyMetricsOpen(false)
    setLatencyTypeOpen(false)
  }, [])

  const toggleSourceFilter = useCallback((source: string) => {
    setSelectedSources((current) => {
      if (current.includes(source)) {
        if (current.length <= 1) {
          return current
        }
        return current.filter((value) => value !== source)
      }
      return [...current, source].sort((a, b) => a.localeCompare(b))
    })
  }, [])

  const selectAllSources = useCallback(() => {
    setSelectedSources(availableSources)
  }, [availableSources])

  const toggleSourcesMenu = useCallback(() => {
    setSourcesOpen((current) => !current)
    setColumnsOpen(false)
    setErrorsCategoryOpen(false)
    setRpsMetricsOpen(false)
    setRpsUsersOpen(false)
    setRpsRangeOpen(false)
    setLatencyMetricsOpen(false)
    setLatencyTypeOpen(false)
  }, [])

  const toggleErrorsCategoryMenu = useCallback(() => {
    setErrorsCategoryOpen((current) => !current)
    setColumnsOpen(false)
    setSourcesOpen(false)
    setRpsMetricsOpen(false)
    setRpsUsersOpen(false)
    setRpsRangeOpen(false)
    setLatencyMetricsOpen(false)
    setLatencyTypeOpen(false)
  }, [])

  const selectErrorsCategory = useCallback((value: string) => {
    setSelectedTracebackCategory(value)
    setErrorsCategoryOpen(false)
  }, [])

  const toggleRpsMetric = useCallback((metricId: string) => {
    setRpsSelectionTouched(true)
    setSelectedRpsMetrics((current) => {
      if (current.includes(metricId)) {
        return current.filter((item) => item !== metricId)
      }
      return [...current, metricId]
    })
  }, [])

  const toggleLatencyMetric = useCallback((metricId: string) => {
    setLatencySelectionTouched(true)
    setSelectedLatencyMetrics((current) => {
      if (current.includes(metricId)) {
        return current.filter((item) => item !== metricId)
      }
      return [...current, metricId]
    })
  }, [])

  const toggleRpsMetricsMenu = useCallback(() => {
    setRpsMetricsOpen((current) => !current)
    setColumnsOpen(false)
    setSourcesOpen(false)
    setErrorsCategoryOpen(false)
    setRpsUsersOpen(false)
    setRpsRangeOpen(false)
    setLatencyMetricsOpen(false)
    setLatencyTypeOpen(false)
  }, [])

  const toggleRpsUsersMenu = useCallback(() => {
    setRpsUsersOpen((current) => !current)
    setColumnsOpen(false)
    setSourcesOpen(false)
    setErrorsCategoryOpen(false)
    setRpsMetricsOpen(false)
    setRpsRangeOpen(false)
    setLatencyMetricsOpen(false)
    setLatencyTypeOpen(false)
  }, [])

  const toggleRpsRangeMenu = useCallback(() => {
    setRpsRangeOpen((current) => !current)
    setColumnsOpen(false)
    setSourcesOpen(false)
    setErrorsCategoryOpen(false)
    setRpsMetricsOpen(false)
    setRpsUsersOpen(false)
    setLatencyMetricsOpen(false)
    setLatencyTypeOpen(false)
  }, [])

  const toggleLatencyMetricsMenu = useCallback(() => {
    setLatencyMetricsOpen((current) => !current)
    setColumnsOpen(false)
    setSourcesOpen(false)
    setErrorsCategoryOpen(false)
    setRpsMetricsOpen(false)
    setRpsUsersOpen(false)
    setRpsRangeOpen(false)
    setLatencyTypeOpen(false)
  }, [])

  const toggleLatencyTypeMenu = useCallback(() => {
    setLatencyTypeOpen((current) => !current)
    setColumnsOpen(false)
    setSourcesOpen(false)
    setErrorsCategoryOpen(false)
    setRpsMetricsOpen(false)
    setRpsUsersOpen(false)
    setRpsRangeOpen(false)
    setLatencyMetricsOpen(false)
  }, [])

  const setChartRange = useCallback((range: ChartRangeId) => {
    setSelectedChartRange(range)
    setRpsRangeOpen(false)
  }, [])

  const selectLatencyType = useCallback((value: LatencySeriesId) => {
    setSelectedLatencyType(value)
    setLatencyTypeOpen(false)
  }, [])

  const selectAllRpsMetrics = useCallback(() => {
    setRpsSelectionTouched(true)
    setSelectedRpsMetrics(availableMetricIds)
  }, [availableMetricIds])

  const clearRpsMetrics = useCallback(() => {
    setRpsSelectionTouched(true)
    setSelectedRpsMetrics([])
  }, [])

  const selectAllLatencyMetrics = useCallback(() => {
    setLatencySelectionTouched(true)
    setSelectedLatencyMetrics(availableMetricIds)
  }, [availableMetricIds])

  const clearLatencyMetrics = useCallback(() => {
    setLatencySelectionTouched(true)
    setSelectedLatencyMetrics([])
  }, [])

  useEffect(() => {
    if (availableSources.length === 0) {
      setSelectedSources([])
      return
    }
    setSelectedSources((current) => {
      const filtered = current.filter((source) => availableSources.includes(source))
      if (filtered.length > 0) {
        return filtered
      }
      return availableSources
    })
  }, [availableSources])

  useEffect(() => {
    if (selectedTracebackCategory === 'all') {
      return
    }
    if (!tracebackCategories.includes(selectedTracebackCategory)) {
      setSelectedTracebackCategory('all')
    }
  }, [selectedTracebackCategory, tracebackCategories])

  useEffect(() => {
    if (typeof ready?.epoch !== 'number') {
      return
    }
    setChartEpoch((current) => (current === ready.epoch ? current : ready.epoch))
  }, [ready?.epoch])

  useEffect(() => {
    if (activeTab !== 'charts') {
      return
    }

    let cancelled = false

    const loadServerChartHistory = async () => {
      try {
        setLoadingServerChartHistory(true)
        const response = await fetchMetricsHistory(selectedChartRange)
        if (cancelled) {
          return
        }
        const mappedPoints = response.points.map(mapServerHistoryPoint)
        setServerChartHistory(mappedPoints)
        lastServerHistoryTsRef.current =
          mappedPoints.length > 0 ? mappedPoints[mappedPoints.length - 1].ts : null
      } catch (historyError) {
        if (cancelled) {
          return
        }
        pushNotification(
          'error',
          historyError instanceof Error
            ? historyError.message
            : 'Failed to load charts history',
        )
      } finally {
        if (!cancelled) {
          setLoadingServerChartHistory(false)
        }
      }
    }

    void loadServerChartHistory()

    return () => {
      cancelled = true
    }
  }, [activeTab, chartEpoch, pushNotification, selectedChartRange])

  useEffect(() => {
    if (activeTab !== 'charts' || selectedChartRange !== 'all' || loadingServerChartHistory) {
      return
    }

    let cancelled = false

    const pullIncrementalHistory = async () => {
      try {
        const fromTs =
          lastServerHistoryTsRef.current === null ? undefined : lastServerHistoryTsRef.current + 1
        const response = await fetchMetricsHistory('all', { fromTs })
        if (cancelled || response.points.length === 0) {
          return
        }

        const mappedPoints = response.points.map(mapServerHistoryPoint)
        setServerChartHistory((current) => {
          const pointsByTs = new Map<number, ChartHistoryPoint>()
          for (const point of current) {
            pointsByTs.set(point.ts, point)
          }
          for (const point of mappedPoints) {
            pointsByTs.set(point.ts, point)
          }
          return Array.from(pointsByTs.values()).sort((a, b) => a.ts - b.ts)
        })
        lastServerHistoryTsRef.current = mappedPoints[mappedPoints.length - 1].ts
      } catch {
        // keep charts responsive even if incremental history fetch fails temporarily
      }
    }

    const timerId = window.setInterval(() => {
      void pullIncrementalHistory()
    }, REFRESH_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(timerId)
    }
  }, [activeTab, loadingServerChartHistory, selectedChartRange])

  useEffect(() => {
    if (
      !columnsOpen &&
      !sourcesOpen &&
      !errorsCategoryOpen &&
      !rpsMetricsOpen &&
      !rpsUsersOpen &&
      !rpsRangeOpen &&
      !latencyMetricsOpen &&
      !latencyTypeOpen
    ) {
      return
    }

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (columnsOpen && !columnsContainerRef.current?.contains(target)) {
        setColumnsOpen(false)
      }
      if (sourcesOpen && !sourcesContainerRef.current?.contains(target)) {
        setSourcesOpen(false)
      }
      if (errorsCategoryOpen && !errorsCategoryContainerRef.current?.contains(target)) {
        setErrorsCategoryOpen(false)
      }
      if (rpsMetricsOpen && !rpsMetricsContainerRef.current?.contains(target)) {
        setRpsMetricsOpen(false)
      }
      if (rpsUsersOpen && !rpsUsersContainerRef.current?.contains(target)) {
        setRpsUsersOpen(false)
      }
      if (rpsRangeOpen && !rpsRangeContainerRef.current?.contains(target)) {
        setRpsRangeOpen(false)
      }
      if (latencyMetricsOpen && !latencyMetricsContainerRef.current?.contains(target)) {
        setLatencyMetricsOpen(false)
      }
      if (latencyTypeOpen && !latencyTypeContainerRef.current?.contains(target)) {
        setLatencyTypeOpen(false)
      }
    }

    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [
    columnsOpen,
    errorsCategoryOpen,
    latencyMetricsOpen,
    latencyTypeOpen,
    rpsMetricsOpen,
    rpsRangeOpen,
    rpsUsersOpen,
    sourcesOpen,
  ])

  useEffect(() => {
    if (!error) {
      if (lastFetchErrorRef.current !== null) {
        pushNotification('success', 'Connection restored.')
      }
      lastFetchErrorRef.current = null
      return
    }

    if (lastFetchErrorRef.current === error) {
      return
    }
    lastFetchErrorRef.current = error
    pushNotification('error', `Failed to fetch data: ${error}`)
  }, [error, pushNotification])

  useEffect(() => {
    const timers = notificationTimersRef.current
    return () => {
      for (const timerId of timers.values()) {
        window.clearTimeout(timerId)
      }
      timers.clear()
    }
  }, [])

  useEffect(() => {
    if (availableMetricIds.length === 0) {
      setSelectedRpsMetrics([])
      return
    }

    setSelectedRpsMetrics((current) => {
      const filtered = current.filter((metricId) => availableMetricIds.includes(metricId))
      if (filtered.length > 0) {
        return filtered
      }
      if (rpsSelectionTouched) {
        return filtered
      }
      return availableMetricIds.slice(0, Math.min(4, availableMetricIds.length))
    })
  }, [availableMetricIds, rpsSelectionTouched])

  useEffect(() => {
    if (availableMetricIds.length === 0) {
      setSelectedLatencyMetrics([])
      return
    }

    setSelectedLatencyMetrics((current) => {
      const filtered = current.filter((metricId) => availableMetricIds.includes(metricId))
      if (filtered.length > 0) {
        return filtered
      }
      if (latencySelectionTouched) {
        return filtered
      }
      return availableMetricIds.slice(0, Math.min(4, availableMetricIds.length))
    })
  }, [availableMetricIds, latencySelectionTouched])

  useEffect(() => {
    if (!startModalOpen) {
      return
    }

    let cancelled = false

    const loadScenario = async () => {
      try {
        setScenarioLoading(true)
        setScenarioError(null)
        const spec = await fetchScenarioOnInitSpec()
        if (cancelled) {
          return
        }
        setScenarioSpec(spec)
        setInitParamValues((current) => {
          const merged = { ...current }
          for (const param of spec.params) {
            if (Object.prototype.hasOwnProperty.call(current, param.name)) {
              continue
            }
            if (param.default === null || param.default === undefined) {
              merged[param.name] = ''
              continue
            }
            if (typeof param.default === 'string') {
              merged[param.name] = param.default
              continue
            }
            merged[param.name] = JSON.stringify(param.default)
          }
          return merged
        })
      } catch (loadError) {
        if (cancelled) {
          return
        }
        setScenarioSpec(null)
        setScenarioError(loadError instanceof Error ? loadError.message : 'Failed to load scenario init params')
      } finally {
        if (!cancelled) {
          setScenarioLoading(false)
        }
      }
    }

    void loadScenario()

    return () => {
      cancelled = true
    }
  }, [startModalOpen])

  return (
    <div className="screen-root">
      <header className="topbar">
        <div className="topbar__brand">
          <Activity size={18} />
          <span>Vikhry</span>
        </div>

        <div className="topbar__status-group">
          <div
            className={`pill pill--state has-tooltip ${statusToneClass(ready?.state)}`}
            data-tooltip={`Status: ${statusLabel(ready?.state)}`}
          >
            <Play size={10} fill="currentColor" />
            <span>{statusLabel(ready?.state)}</span>
          </div>
          <div className="pill has-tooltip" data-tooltip="Active users on alive workers">
            <Users size={12} />
            <span>{numberFormatter.format(totalUsers)}</span>
          </div>
          <div className="pill has-tooltip" data-tooltip="Alive workers">
            <Gauge size={12} />
            <span>{numberFormatter.format(ready?.alive_workers ?? 0)}</span>
          </div>
          <div className="pill has-tooltip" data-tooltip="Current total RPS">
            <Activity size={12} />
            <span>{compactNumberFormatter.format(totalRps)} RPS</span>
          </div>
          {elapsedSeconds !== null ? (
            <div className="pill has-tooltip" data-tooltip="Test duration">
              <Clock3 size={12} />
              <span>{formatElapsed(elapsedSeconds)}</span>
            </div>
          ) : null}
        </div>

        <div className="topbar__actions">
          {canStart ? (
            <button
              className="btn btn--primary has-tooltip"
              type="button"
              onClick={() => setStartModalOpen(true)}
              data-tooltip="Start test run"
            >
              <Play size={12} />
              <span>Start</span>
            </button>
          ) : null}
          {canStop ? (
            <button
              className="btn btn--primary has-tooltip"
              disabled={stopping}
              onClick={() => void onStop()}
              type="button"
              data-tooltip={stopping ? 'Stopping test run...' : 'Stop test run'}
            >
              <Square size={12} />
              <span>{stopping ? 'Stopping...' : 'Stop'}</span>
            </button>
          ) : null}
          {canChangeUsers ? (
            <button
              className="btn has-tooltip"
              type="button"
              onClick={openChangeUsersModal}
              data-tooltip="Change target users"
            >
              <Users size={12} />
              <span>Change users</span>
            </button>
          ) : null}
          <button
            className="btn has-tooltip"
            type="button"
            onClick={() => openResourceModal()}
            data-tooltip="Create resources"
          >
            <Layers size={12} />
            <span>Create resources</span>
          </button>
        </div>
      </header>

      <nav className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={tab.id === activeTab ? 'tab tab--active' : 'tab'}
            type="button"
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="content">
        {activeTab === 'statistics' ? (
          <>
            <section className="section-header">
              <h1>Test Statistics</h1>
              <div className="statistics-controls">
                <div className="stats-scope-toggle" role="group" aria-label="Statistics scope">
                  <button
                    type="button"
                    onClick={() => setStatsScope('window')}
                    aria-pressed={statsScope === 'window'}
                    data-tooltip="Show metrics for rolling time window"
                    className={
                      statsScope === 'window'
                        ? 'stats-scope-toggle__btn stats-scope-toggle__btn--active has-tooltip'
                        : 'stats-scope-toggle__btn has-tooltip'
                    }
                  >
                    Window
                  </button>
                  <button
                    type="button"
                    onClick={() => setStatsScope('total')}
                    aria-pressed={statsScope === 'total'}
                    data-tooltip="Show cumulative metrics for whole test run"
                    className={
                      statsScope === 'total'
                        ? 'stats-scope-toggle__btn stats-scope-toggle__btn--active has-tooltip'
                        : 'stats-scope-toggle__btn has-tooltip'
                    }
                  >
                    Whole test
                  </button>
                </div>

                <div className="columns-control" ref={columnsContainerRef}>
                  <button className="btn" type="button" onClick={toggleColumnsMenu}>
                    <Columns3 size={12} />
                    <span>Columns</span>
                    <ChevronDown size={12} />
                  </button>
                  {columnsOpen ? (
                    <div className="columns-menu">
                      {statsColumns.map((column) => (
                        <label key={column.id} className="columns-menu__item">
                          <input
                            type="checkbox"
                            checked={visibleColumns.includes(column.id)}
                            disabled={column.required}
                            onChange={() => toggleColumn(column.id)}
                          />
                          <span>{column.label}</span>
                        </label>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="table-card">
              <table>
                <thead>
                  <tr>
                    {statsColumns
                      .filter((column) => visibleColumns.includes(column.id))
                      .map((column) => (
                        <th key={column.id}>{column.label}</th>
                      ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td className="table-empty" colSpan={visibleColumns.length}>
                        No data
                      </td>
                    </tr>
                  ) : (
                    rows
                      .filter((row) => !row.isNested || !row.parentName || !collapsedGroups.has(row.parentName))
                      .map((row) => (
                      <tr key={row.isNested ? `${row.parentName}/${row.name}` : row.name}>
                        {visibleColumns.includes('name') ? (
                          <td className={row.isNested ? 'stats-name-cell stats-name-cell--nested' : 'stats-name-cell'}>
                            {row.hasChildren ? (
                              <button
                                type="button"
                                className="stats-collapse-btn"
                                onClick={() => setCollapsedGroups((prev) => {
                                  const next = new Set(prev)
                                  if (next.has(row.name)) {
                                    next.delete(row.name)
                                  } else {
                                    next.add(row.name)
                                  }
                                  return next
                                })}
                              >
                                {collapsedGroups.has(row.name) ? '▶' : '▼'}
                              </button>
                            ) : null}
                            {row.name}
                          </td>
                        ) : null}
                        {visibleColumns.includes('success') ? <td>{numberFormatter.format(row.success)}</td> : null}
                        {visibleColumns.includes('failure') ? <td>{numberFormatter.format(row.failure)}</td> : null}
                        {visibleColumns.includes('medianMs') ? <td>{formatMaybeNumber(row.medianMs)}</td> : null}
                        {visibleColumns.includes('p95Ms') ? <td>{formatMaybeNumber(row.p95Ms)}</td> : null}
                        {visibleColumns.includes('p99Ms') ? <td>{formatMaybeNumber(row.p99Ms)}</td> : null}
                        {visibleColumns.includes('averageMs') ? (
                          <td>{formatMaybeNumber(row.averageMs)}</td>
                        ) : null}
                        {visibleColumns.includes('rps') ? <td>{formatMaybeNumber(row.rps, 1)}</td> : null}
                        {visibleColumns.includes('failureRate') ? (
                          <td style={failureRateStyle(row.failureRate)}>{(row.failureRate * 100).toFixed(2)}%</td>
                        ) : null}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </section>

            <section className="error-breakdown">
              <div className="error-breakdown__header">
                <h2>Error Breakdown</h2>
                <div className="columns-control" ref={sourcesContainerRef}>
                  <button className="btn" type="button" onClick={toggleSourcesMenu}>
                    <span>{selectedSourcesSummary}</span>
                    <ChevronDown size={12} />
                  </button>
                  {sourcesOpen ? (
                    <div className="columns-menu">
                      <button
                        type="button"
                        className="columns-menu__action"
                        onClick={selectAllSources}
                        disabled={
                          availableSources.length === 0 ||
                          selectedSources.length === availableSources.length
                        }
                      >
                        All sources
                      </button>
                      {availableSources.map((source) => (
                        <label key={source} className="columns-menu__item">
                          <input
                            type="checkbox"
                            checked={selectedSources.includes(source)}
                            onChange={() => toggleSourceFilter(source)}
                          />
                          <span>{source}</span>
                        </label>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="error-summary-grid">
                <article className="error-summary-card">
                  <p className="error-summary-card__label">Requests</p>
                  <p className="error-summary-card__value">
                    {numberFormatter.format(errorBreakdown.totalRequests)}
                  </p>
                </article>
                <article className="error-summary-card">
                  <p className="error-summary-card__label">Errors</p>
                  <p className="error-summary-card__value">
                    {numberFormatter.format(errorBreakdown.totalErrors)}
                  </p>
                </article>
                <article
                  className={
                    errorBreakdown.totalFatal > 0
                      ? 'error-summary-card error-summary-card--fatal'
                      : 'error-summary-card'
                  }
                >
                  <p className="error-summary-card__label">Fatal</p>
                  <p className="error-summary-card__value">
                    {numberFormatter.format(errorBreakdown.totalFatal)}
                  </p>
                </article>
                <article className="error-summary-card">
                  <p className="error-summary-card__label">Failure Rate</p>
                  <p className="error-summary-card__value">
                    {errorBreakdown.totalRequests > 0
                      ? `${((errorBreakdown.totalErrors / errorBreakdown.totalRequests) * 100).toFixed(2)}%`
                      : '0.00%'}
                  </p>
                </article>
              </div>

              <div className="error-breakdown-grid">
                <article className="error-panel">
                  <header className="error-panel__header">
                    <h3>Top Result Codes</h3>
                  </header>
                  {errorBreakdown.resultCodeRows.length === 0 ? (
                    <p className="error-panel__empty">No result codes in selected scope.</p>
                  ) : (
                    <ul className="error-list">
                      {errorBreakdown.resultCodeRows.slice(0, 10).map((row) => (
                        <li key={row.label} className="error-list__row">
                          <span className="error-list__label">{row.label}</span>
                          <span className="error-list__value">{numberFormatter.format(row.count)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>

                <article className="error-panel">
                  <header className="error-panel__header">
                    <h3>Result Categories</h3>
                  </header>
                  {errorBreakdown.resultCategoryRows.length === 0 ? (
                    <p className="error-panel__empty">No categories in selected scope.</p>
                  ) : (
                    <ul className="error-list">
                      {errorBreakdown.resultCategoryRows.slice(0, 10).map((row) => (
                        <li key={row.label} className="error-list__row">
                          <span className="error-list__label">{row.label}</span>
                          <span className="error-list__value">{numberFormatter.format(row.count)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>

                <article className="error-panel">
                  <header className="error-panel__header">
                    <h3>By Source</h3>
                  </header>
                  {errorBreakdown.sourceRows.length === 0 ? (
                    <p className="error-panel__empty">No source data in selected scope.</p>
                  ) : (
                    <ul className="error-list">
                      {errorBreakdown.sourceRows.map((row) => (
                        <li key={row.source} className="error-list__row error-list__row--source">
                          <span className="error-list__label">{row.source}</span>
                          <span className="error-list__meta">
                            {numberFormatter.format(row.errors)} err / {numberFormatter.format(row.requests)} req
                          </span>
                          <span className="error-list__value">{numberFormatter.format(row.fatal)} fatal</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              </div>
            </section>
          </>
        ) : null}

        {activeTab === 'errors' ? (
          <>
            <section className="section-header">
              <h1>Errors</h1>
              <div className="columns-control errors-controls" ref={errorsCategoryContainerRef}>
                <button className="btn" type="button" onClick={toggleErrorsCategoryMenu}>
                  <span>{selectedErrorsCategoryLabel}</span>
                  <ChevronDown size={12} />
                </button>
                {errorsCategoryOpen ? (
                  <div className="columns-menu">
                    <button
                      type="button"
                      className={
                        selectedTracebackCategory === 'all'
                          ? 'columns-menu__option columns-menu__option--active'
                          : 'columns-menu__option'
                      }
                      onClick={() => selectErrorsCategory('all')}
                    >
                      All categories
                    </button>
                    {tracebackCategories.map((category) => (
                      <button
                        key={category}
                        type="button"
                        className={
                          selectedTracebackCategory === category
                            ? 'columns-menu__option columns-menu__option--active'
                            : 'columns-menu__option'
                        }
                        onClick={() => selectErrorsCategory(category)}
                      >
                        {category}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </section>

            <section className="table-card errors-table-card">
              <table className="errors-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Category</th>
                    <th>Source</th>
                    <th>Metric</th>
                    <th>Traceback</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTracebackRows.length === 0 ? (
                    <tr>
                      <td className="table-empty" colSpan={5}>
                        No data
                      </td>
                    </tr>
                  ) : (
                    filteredTracebackRows.map((row) => (
                      <tr key={row.key}>
                        <td>{formatEventTimestamp(row.timestampMs)}</td>
                        <td>{row.category}</td>
                        <td>{row.source}</td>
                        <td>
                          <div className="errors-metric-cell">
                            <span className="errors-metric-cell__name">{row.metricId}</span>
                            <span className="errors-metric-cell__meta">{row.stage}</span>
                          </div>
                        </td>
                        <td className="errors-traceback-cell">
                          {row.errorType || row.errorMessage ? (
                            <p className="errors-traceback-meta" title={[row.errorType, row.errorMessage].filter(Boolean).join(': ')}>
                              {[row.errorType, row.errorMessage].filter(Boolean).join(': ')}
                            </p>
                          ) : null}
                          {row.traceback ? (
                            <TracebackBlock content={row.traceback} />
                          ) : null}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </section>
          </>
        ) : null}

        {activeTab === 'resources' ? (
          <>
            <section className="section-header">
              <h1>Resources</h1>
            </section>

            <section className="table-card">
              <table>
                <thead>
                  <tr>
                    <th>Resource Name</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {!resources || resources.resources.length === 0 ? (
                    <tr>
                      <td className="table-empty" colSpan={3}>
                        No data
                      </td>
                    </tr>
                  ) : (
                    resources.resources.map((resource) => (
                      <tr key={resource.resource_name}>
                        <td>{resource.resource_name}</td>
                        <td>{numberFormatter.format(resource.count)}</td>
                        <td>
                          <button
                            className="btn btn--ghost table-action-btn"
                            type="button"
                            onClick={() => {
                              setResourceViewName(resource.resource_name)
                              setResourceViewModalOpen(true)
                            }}
                          >
                            View
                          </button>
                          <button
                            className="btn btn--ghost table-action-btn"
                            type="button"
                            onClick={() => openResourceModal(resource.resource_name)}
                          >
                            Create
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </section>
          </>
        ) : null}

        {activeTab === 'workers' ? (
          <>
            <section className="section-header">
              <h1>Active Workers</h1>
            </section>

            <section className="table-card">
              <table>
                <thead>
                  <tr>
                    <th>Worker ID</th>
                    <th>Healthcheck</th>
                    <th>Last Seen</th>
                    <th>Users</th>
                    <th>CPU Load</th>
                    <th>RAM Load</th>
                  </tr>
                </thead>
                <tbody>
                  {workerRows.length === 0 ? (
                    <tr>
                      <td className="table-empty" colSpan={6}>
                        No data
                      </td>
                    </tr>
                  ) : (
                    workerRows.map(({ worker, badge, usersSummary, cpuLoad, ramLoad, ramUsage }) => (
                      <tr key={worker.worker_id}>
                        <td>{worker.worker_id}</td>
                        <td>
                          <span className={`worker-badge worker-badge--${badge.tone}`}>
                            <span className="worker-badge__dot" />
                            {badge.label}
                          </span>
                        </td>
                        <td>
                          <span
                            className={
                              (worker.heartbeat_age_s ?? 0) > 30 ? 'worker-last-seen worker-last-seen--late' : 'worker-last-seen'
                            }
                          >
                            {formatLastSeen(worker.heartbeat_age_s)}
                          </span>
                        </td>
                        <td>{usersSummary}</td>
                        <td>
                          {cpuLoad === null ? (
                            <span className="load-unavailable">—</span>
                          ) : (
                            <div className="load-cell">
                              <div className="load-track">
                                <div
                                  className={`load-fill load-fill--${loadTone(cpuLoad)}`}
                                  style={{ width: `${cpuLoad}%` }}
                                />
                              </div>
                              <span>{cpuLoad}%</span>
                            </div>
                          )}
                        </td>
                        <td>
                          {ramLoad === null ? (
                            <span className="load-unavailable">—</span>
                          ) : (
                            <div className="load-cell">
                              <div className="load-track">
                                <div
                                  className={`load-fill load-fill--${loadTone(ramLoad)}`}
                                  style={{ width: `${ramLoad}%` }}
                                />
                              </div>
                              <span>{ramUsage ?? '—'}</span>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </section>
          </>
        ) : null}

        {activeTab === 'charts' ? (
          <>
            <section className="section-header">
              <h1>Test Charts</h1>
              <div className="columns-control" ref={rpsRangeContainerRef}>
                <button className="btn" type="button" onClick={toggleRpsRangeMenu}>
                  <span>{selectedChartRangeLabel}</span>
                  <ChevronDown size={12} />
                </button>
                {rpsRangeOpen ? (
                  <div className="columns-menu">
                    {chartRanges.map((range) => (
                      <button
                        key={range.id}
                        type="button"
                        className={
                          selectedChartRange === range.id
                            ? 'columns-menu__option columns-menu__option--active'
                            : 'columns-menu__option'
                        }
                        onClick={() => setChartRange(range.id)}
                      >
                        {range.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </section>

            <section className="chart-grid">
              <article className="chart-card">
                <header className="chart-card__header">
                  <h2>Requests Per Second (RPS)</h2>
                  <div className="chart-card__actions chart-card__actions--dropdowns">
                    <div className="columns-control" ref={rpsUsersContainerRef}>
                      <button className="btn btn--ghost" type="button" onClick={toggleRpsUsersMenu}>
                        <span>{showUsersOnRpsChart ? 'Users: On' : 'Users: Off'}</span>
                        <ChevronDown size={12} />
                      </button>
                      {rpsUsersOpen ? (
                        <div className="columns-menu">
                          <button
                            type="button"
                            className={
                              showUsersOnRpsChart
                                ? 'columns-menu__option columns-menu__option--active'
                                : 'columns-menu__option'
                            }
                            onClick={() => {
                              setShowUsersOnRpsChart(true)
                              setRpsUsersOpen(false)
                            }}
                          >
                            Show users
                          </button>
                          <button
                            type="button"
                            className={
                              !showUsersOnRpsChart
                                ? 'columns-menu__option columns-menu__option--active'
                                : 'columns-menu__option'
                            }
                            onClick={() => {
                              setShowUsersOnRpsChart(false)
                              setRpsUsersOpen(false)
                            }}
                          >
                            Hide users
                          </button>
                        </div>
                      ) : null}
                    </div>

                    <div className="columns-control" ref={rpsMetricsContainerRef}>
                      <button className="btn btn--ghost" type="button" onClick={toggleRpsMetricsMenu}>
                        <span>{selectedRpsMetricsSummary}</span>
                        <ChevronDown size={12} />
                      </button>
                      {rpsMetricsOpen ? (
                        <div className="columns-menu chart-menu">
                          <div className="chart-menu__actions">
                            <button type="button" className="columns-menu__action" onClick={selectAllRpsMetrics}>
                              Select all
                            </button>
                            <button type="button" className="columns-menu__action" onClick={clearRpsMetrics}>
                              Clear
                            </button>
                          </div>

                          {['step', 'http', 'other'].map((group) => {
                            const groupOptions = availableMetricOptions.filter((option) =>
                              group === 'other'
                                ? option.source !== 'step' && option.source !== 'http'
                                : option.source === group,
                            )
                            if (groupOptions.length === 0) {
                              return null
                            }

                            const groupLabel =
                              group === 'step' ? 'Step metrics' : group === 'http' ? 'HTTP metrics' : 'Other metrics'

                            return (
                              <div key={group} className="chart-menu__group">
                                <p className="chart-menu__group-label">{groupLabel}</p>
                                {groupOptions.map((option) => (
                                  <label key={option.id} className="columns-menu__item">
                                    <input
                                      type="checkbox"
                                      checked={selectedRpsMetrics.includes(option.id)}
                                      onChange={() => toggleRpsMetric(option.id)}
                                    />
                                    <span>{option.id}</span>
                                  </label>
                                ))}
                              </div>
                            )
                          })}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </header>

                <div className="chart-canvas">
                  {rpsChartData.length === 0 || (selectedRpsMetrics.length === 0 && !showUsersOnRpsChart) ? (
                    <p className="chart-empty">
                      {loadingServerChartHistory
                        ? 'Loading chart history...'
                        : 'Select metrics or enable users line.'}
                    </p>
                  ) : (
                    <ResponsiveContainer width="100%" height={290}>
                      <LineChart data={rpsChartData}>
                        <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" />
                        <XAxis
                          dataKey="tsMs"
                          type="number"
                          domain={['dataMin', 'dataMax']}
                          tick={{ fontSize: 11, fill: '#94a3b8' }}
                          tickFormatter={(value) => formatChartTime(Math.floor(Number(value) / 1000))}
                          minTickGap={24}
                        />
                        <YAxis yAxisId="rps" domain={[0, 'auto']} tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        {showUsersOnRpsChart ? (
                          <YAxis
                            yAxisId="users"
                            orientation="right"
                            domain={[0, 'auto']}
                            tick={{ fontSize: 11, fill: '#7c3aed' }}
                          />
                        ) : null}
                        <Tooltip
                          contentStyle={{
                            borderRadius: 8,
                            border: '1px solid #e2e8f0',
                            fontSize: 12,
                          }}
                          labelFormatter={(value) => formatChartTime(Math.floor(Number(value) / 1000))}
                          formatter={(value, name) => {
                            const numeric = typeof value === 'number' ? value : Number(value)
                            if (!Number.isFinite(numeric)) {
                              return '—'
                            }
                            if (name === 'Users') {
                              return `${numberFormatter.format(Math.round(numeric))} users`
                            }
                            return `${numeric.toFixed(1)} RPS`
                          }}
                        />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        {selectedRpsMetrics.map((metricId, index) => (
                          <Line
                            key={metricId}
                            type="monotone"
                            dataKey={metricId}
                            yAxisId="rps"
                            name={metricId}
                            stroke={rpsLinePalette[index % rpsLinePalette.length]}
                            strokeWidth={2}
                            dot={false}
                            isAnimationActive={false}
                            connectNulls
                          />
                        ))}
                        {showUsersOnRpsChart ? (
                          <>
                            <Line
                              type="stepAfter"
                              dataKey="__users"
                              yAxisId="users"
                              name="Users"
                              stroke="#7c3aed"
                              strokeWidth={2}
                              dot={false}
                              isAnimationActive={false}
                              connectNulls
                            />
                            <Line
                              type="linear"
                              dataKey="__usersChangeMarker"
                              yAxisId="users"
                              name="Users changed"
                              stroke="transparent"
                              strokeWidth={0}
                              dot={{ r: 3, fill: '#7c3aed', strokeWidth: 0 }}
                              activeDot={false}
                              isAnimationActive={false}
                              connectNulls={false}
                              legendType="none"
                            />
                          </>
                        ) : null}
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </article>

              <article className="chart-card">
                <header className="chart-card__header">
                  <h2>Latency (ms)</h2>
                  <div className="chart-card__actions chart-card__actions--dropdowns">
                    <div className="columns-control" ref={latencyTypeContainerRef}>
                      <button className="btn btn--ghost" type="button" onClick={toggleLatencyTypeMenu}>
                        <span>{selectedLatencyLabel}</span>
                        <ChevronDown size={12} />
                      </button>
                      {latencyTypeOpen ? (
                        <div className="columns-menu">
                          {latencySeriesMeta.map((series) => (
                            <button
                              key={series.id}
                              type="button"
                              className={
                                selectedLatencyType === series.id
                                  ? 'columns-menu__option columns-menu__option--active'
                                  : 'columns-menu__option'
                              }
                              onClick={() => selectLatencyType(series.id)}
                            >
                              {series.label}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>

                    <div className="columns-control" ref={latencyMetricsContainerRef}>
                      <button className="btn btn--ghost" type="button" onClick={toggleLatencyMetricsMenu}>
                        <span>{selectedLatencyMetricsSummary}</span>
                        <ChevronDown size={12} />
                      </button>
                      {latencyMetricsOpen ? (
                        <div className="columns-menu chart-menu">
                          <div className="chart-menu__actions">
                            <button type="button" className="columns-menu__action" onClick={selectAllLatencyMetrics}>
                              Select all
                            </button>
                            <button type="button" className="columns-menu__action" onClick={clearLatencyMetrics}>
                              Clear
                            </button>
                          </div>

                          {['step', 'http', 'other'].map((group) => {
                            const groupOptions = availableMetricOptions.filter((option) =>
                              group === 'other'
                                ? option.source !== 'step' && option.source !== 'http'
                                : option.source === group,
                            )
                            if (groupOptions.length === 0) {
                              return null
                            }

                            const groupLabel =
                              group === 'step' ? 'Step metrics' : group === 'http' ? 'HTTP metrics' : 'Other metrics'

                            return (
                              <div key={group} className="chart-menu__group">
                                <p className="chart-menu__group-label">{groupLabel}</p>
                                {groupOptions.map((option) => (
                                  <label key={option.id} className="columns-menu__item">
                                    <input
                                      type="checkbox"
                                      checked={selectedLatencyMetrics.includes(option.id)}
                                      onChange={() => toggleLatencyMetric(option.id)}
                                    />
                                    <span>{option.id}</span>
                                  </label>
                                ))}
                              </div>
                            )
                          })}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </header>

                <div className="chart-canvas">
                  {latencyChartData.length === 0 || selectedLatencyMetrics.length === 0 ? (
                    <p className="chart-empty">
                      {loadingServerChartHistory
                        ? 'Loading chart history...'
                        : 'Select metrics for latency chart.'}
                    </p>
                  ) : (
                    <ResponsiveContainer width="100%" height={290}>
                      <LineChart data={latencyChartData}>
                        <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" />
                        <XAxis
                          dataKey="tsMs"
                          type="number"
                          domain={['dataMin', 'dataMax']}
                          tick={{ fontSize: 11, fill: '#94a3b8' }}
                          tickFormatter={(value) => formatChartTime(Math.floor(Number(value) / 1000))}
                          minTickGap={24}
                        />
                        <YAxis domain={[0, 'auto']} tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        <Tooltip
                          contentStyle={{
                            borderRadius: 8,
                            border: '1px solid #e2e8f0',
                            fontSize: 12,
                          }}
                          labelFormatter={(value) => formatChartTime(Math.floor(Number(value) / 1000))}
                          formatter={(value) => {
                            const numeric = typeof value === 'number' ? value : Number(value)
                            if (!Number.isFinite(numeric)) {
                              return '—'
                            }
                            return `${numeric.toFixed(1)} ms`
                          }}
                        />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        {selectedLatencyMetrics.map((metricId, index) => (
                          <Line
                            key={metricId}
                            type="monotone"
                            dataKey={metricId}
                            name={metricId}
                            stroke={rpsLinePalette[index % rpsLinePalette.length]}
                            strokeWidth={2}
                            dot={false}
                            isAnimationActive={false}
                            connectNulls
                          />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </article>
            </section>
          </>
        ) : null}

        {activeTab === 'probes' ? <ProbeChartsPanel /> : null}
      </main>

      <section className="notification-stack" aria-live="polite" aria-atomic="true">
        {notifications.map((item) => (
          <article
            key={item.id}
            className={`notification notification--${item.tone}`}
            role={item.tone === 'error' ? 'alert' : 'status'}
          >
            <p className="notification__message">{item.message}</p>
            <button
              className="notification__close"
              type="button"
              aria-label="Dismiss notification"
              onClick={() => dismissNotification(item.id)}
            >
              <X size={13} />
            </button>
          </article>
        ))}
      </section>

      {startModalOpen ? (
        <div className="modal-overlay" role="presentation" onClick={() => setStartModalOpen(false)}>
          <section className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <header className="modal__header">
              <h2>Launch Test</h2>
              <button className="modal__close" type="button" onClick={() => setStartModalOpen(false)}>
                <X size={14} />
              </button>
            </header>

            <div className="modal__content">
              <label className="field">
                <span className="field__label">Users</span>
                <input
                  className="field__input"
                  type="number"
                  min={0}
                  step={1}
                  value={targetUsersInput}
                  onChange={(event) => setTargetUsersInput(event.target.value)}
                />
                <span className="field__hint">Maximum concurrent users for this test run.</span>
              </label>

              <section className="params-card">
                <h3>Initialize parameters</h3>
                {scenarioLoading ? <p className="params-card__state">Loading scenario params...</p> : null}
                {scenarioError ? <p className="params-card__state params-card__state--error">{scenarioError}</p> : null}
                {!scenarioLoading && !scenarioError && scenarioSpec && scenarioSpec.params.length === 0 ? (
                  <p className="params-card__state">Scenario does not require init params.</p>
                ) : null}
                {!scenarioLoading && !scenarioError && scenarioSpec
                  ? scenarioSpec.params.map((param) => (
                      <label className="field field--compact" key={param.name}>
                        <span className="field__label">
                          {param.name}
                          {param.required ? ' *' : ''}
                        </span>
                        <input
                          className="field__input"
                          value={initParamValues[param.name] ?? ''}
                          onChange={(event) =>
                            setInitParamValues((current) => ({
                              ...current,
                              [param.name]: event.target.value,
                            }))
                          }
                        />
                        <span className="field__hint">
                          {param.annotation ? `type: ${param.annotation}` : 'any JSON-compatible value'}
                        </span>
                      </label>
                    ))
                  : null}
              </section>
            </div>

            <footer className="modal__footer">
              <button className="btn" type="button" onClick={() => setStartModalOpen(false)}>
                Cancel
              </button>
              <button className="btn btn--primary" type="button" onClick={() => void onStart()} disabled={starting}>
                <Play size={12} />
                <span>{starting ? 'Starting...' : 'Start Test'}</span>
              </button>
            </footer>
          </section>
        </div>
      ) : null}

      {changeUsersModalOpen ? (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={() => {
            if (!changingUsers) {
              setChangeUsersModalOpen(false)
            }
          }}
        >
          <section
            className="modal modal--sm"
            role="dialog"
            aria-modal="true"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="modal__header">
              <h2>Change Users</h2>
              <button
                className="modal__close"
                type="button"
                onClick={() => setChangeUsersModalOpen(false)}
                disabled={changingUsers}
              >
                <X size={14} />
              </button>
            </header>

            <div className="modal__content">
              <label className="field">
                <span className="field__label">Users</span>
                <input
                  className="field__input"
                  type="number"
                  min={0}
                  step={1}
                  value={changeUsersInput}
                  onChange={(event) => setChangeUsersInput(event.target.value)}
                />
                <span className="field__hint">Target concurrent users for current running test.</span>
              </label>
            </div>

            <footer className="modal__footer">
              <button
                className="btn"
                type="button"
                onClick={() => setChangeUsersModalOpen(false)}
                disabled={changingUsers}
              >
                Cancel
              </button>
              <button
                className="btn btn--primary"
                type="button"
                onClick={() => void onChangeUsers()}
                disabled={changingUsers}
              >
                <Users size={12} />
                <span>{changingUsers ? 'Applying...' : 'Change users'}</span>
              </button>
            </footer>
          </section>
        </div>
      ) : null}

      <ResourceCreateModal
        open={resourceModalOpen}
        resourceNames={resourceNames}
        resourceCounts={resourceCounts}
        selectedResourceName={selectedResourceName}
        countValue={resourceCountInput}
        creating={creatingResource}
        onClose={() => setResourceModalOpen(false)}
        onResourceChange={setResourceNameInput}
        onCountChange={setResourceCountInput}
        onCreate={onCreateResource}
      />

      <ResourceViewModal
        open={resourceViewModalOpen}
        resourceName={resourceViewName}
        onClose={() => setResourceViewModalOpen(false)}
      />
    </div>
  )
}
