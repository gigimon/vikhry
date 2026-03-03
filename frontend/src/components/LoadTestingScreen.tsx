import {
  Activity,
  ChevronDown,
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
  fetchReady,
  fetchResources,
  fetchScenarioOnInitSpec,
  fetchWorkers,
  startTest,
  stopTest,
} from '../api/dashboardApi'
import { ResourceCreateModal } from './ResourceCreateModal'
import type {
  MetricsResponse,
  ReadyResponse,
  ResourcesResponse,
  ScenarioOnInitSpec,
  StatsRow,
  WorkersResponse,
} from '../types/dashboard'

const REFRESH_INTERVAL_MS = 2_000
const ERROR_EVENTS_FETCH_COUNT = 1000

type TabId = 'statistics' | 'charts' | 'errors' | 'resources' | 'workers'
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
type NotificationTone = 'info' | 'success' | 'error'

interface ChartHistoryPoint {
  ts: number
  totalUsers: number
  rpsByMetric: Record<string, number>
  latencyByType: Record<LatencySeriesId, number | null>
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
const HISTORY_WINDOW_S = 15 * 60
const NOTIFICATION_TTL_MS = 4_500
const ERROR_NOTIFICATION_TTL_MS = 7_000
const rpsLinePalette = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
const latencySeriesMeta: Array<{ id: LatencySeriesId; label: string; color: string }> = [
  { id: 'averageMs', label: 'Average', color: '#8b5cf6' },
  { id: 'medianMs', label: 'Median', color: '#22c55e' },
  { id: 'p95Ms', label: 'P95', color: '#f59e0b' },
  { id: 'p99Ms', label: 'P99', color: '#ef4444' },
]

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

function isHttpMetric(metric: MetricsResponse['metrics'][number]): boolean {
  const kind = metricKind(metric)
  return kind === 'http'
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

function toStatsRows(metrics: MetricsResponse | null, scope: StatsScope): StatsRow[] {
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
    const eventData = latestMetricEventData(item)
    const kind = metricKind(item)
    const stepName = normalizedString(eventData?.step ?? null)
    const isStepMetric = kind === 'step' && stepName !== null && item.metric_id === stepName

    return {
      metricId: item.metric_id,
      name: item.metric_id,
      success,
      failure,
      medianMs: aggregate.latency_median_ms,
      p95Ms: aggregate.latency_p95_ms,
      p99Ms: aggregate.latency_p99_ms,
      averageMs: aggregate.latency_avg_ms,
      rps: aggregate.rps,
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

    if (row.kind === 'http' && row.stepName !== null && row.stepName !== '__unknown__') {
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
    topLevelRows.push(...childRows)
  }

  topLevelRows.sort(metricSortByName)

  const output: StatsRow[] = []
  for (const row of topLevelRows) {
    output.push({ ...row, isNested: false })

    if (!row.isStepMetric) {
      continue
    }

    const children = [...(httpRowsByStep.get(row.metricId) ?? [])]
    children.sort(metricSortByName)
    for (const child of children) {
      output.push({ ...child, isNested: true })
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

function aggregateLatencyByRps(
  metrics: MetricsResponse,
  field: 'latency_avg_ms' | 'latency_median_ms' | 'latency_p95_ms' | 'latency_p99_ms',
): number | null {
  let weightedSum = 0
  let totalWeight = 0

  for (const metric of metrics.metrics) {
    const value = metric.aggregate[field]
    if (value === null) {
      continue
    }
    const weight = Math.max(metric.aggregate.rps, 1)
    weightedSum += value * weight
    totalWeight += weight
  }

  if (totalWeight <= 0) {
    return null
  }
  return roundTo(weightedSum / totalWeight)
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
): ChartHistoryPoint {
  const totalUsers = sumUsersForActiveWorkers(workers, activeWorkerIds)
  const rpsByMetric: Record<string, number> = {}
  for (const metric of metrics.metrics) {
    rpsByMetric[metric.metric_id] = roundTo(metric.aggregate.rps)
  }

  return {
    ts: generatedAt,
    totalUsers,
    rpsByMetric,
    latencyByType: {
      averageMs: aggregateLatencyByRps(metrics, 'latency_avg_ms'),
      medianMs: aggregateLatencyByRps(metrics, 'latency_median_ms'),
      p95Ms: aggregateLatencyByRps(metrics, 'latency_p95_ms'),
      p99Ms: aggregateLatencyByRps(metrics, 'latency_p99_ms'),
    },
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
  const [history, setHistory] = useState<ChartHistoryPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)

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

    if (metricsResult.status === 'fulfilled') {
      setMetrics(metricsResult.value)
    } else {
      pushError('metrics', metricsResult.reason)
    }

    if (metricsResult.status === 'fulfilled' && workersResult.status === 'fulfilled') {
      const ts =
        metricsResult.value.generated_at > 0
          ? metricsResult.value.generated_at
          : Math.floor(Date.now() / 1000)
      const activeWorkerIds = readyResult.status === 'fulfilled' ? readyResult.value.workers : null
      const point = buildHistoryPoint(metricsResult.value, workersResult.value, activeWorkerIds, ts)
      setHistory((current) => {
        const merged =
          current.length > 0 && current[current.length - 1].ts === point.ts
            ? [...current.slice(0, -1), point]
            : [...current, point]
        return merged.filter((item) => ts - item.ts <= HISTORY_WINDOW_S).slice(-600)
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
    history,
    loading,
    refreshing,
    error,
    refresh,
  }
}

export function LoadTestingScreen() {
  const [activeTab, setActiveTab] = useState<TabId>('statistics')
  const [statsScope, setStatsScope] = useState<StatsScope>('window')
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [visibleColumns, setVisibleColumns] = useState<StatsColumnId[]>(defaultVisibleColumns)
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [errorsCategoryOpen, setErrorsCategoryOpen] = useState(false)

  const [startModalOpen, setStartModalOpen] = useState(false)
  const [changeUsersModalOpen, setChangeUsersModalOpen] = useState(false)
  const [resourceModalOpen, setResourceModalOpen] = useState(false)

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
  const [latencySeriesSelection, setLatencySeriesSelection] = useState<
    Record<LatencySeriesId, { enabled: boolean; users: string }>
  >({
    averageMs: { enabled: true, users: 'all' },
    medianMs: { enabled: false, users: 'all' },
    p95Ms: { enabled: true, users: 'all' },
    p99Ms: { enabled: true, users: 'all' },
  })

  const [scenarioSpec, setScenarioSpec] = useState<ScenarioOnInitSpec | null>(null)
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioError, setScenarioError] = useState<string | null>(null)
  const [initParamValues, setInitParamValues] = useState<Record<string, string>>({})
  const [selectedTracebackCategory, setSelectedTracebackCategory] = useState('all')

  const columnsContainerRef = useRef<HTMLDivElement | null>(null)
  const sourcesContainerRef = useRef<HTMLDivElement | null>(null)
  const errorsCategoryContainerRef = useRef<HTMLDivElement | null>(null)
  const notificationIdRef = useRef(0)
  const notificationTimersRef = useRef<Map<number, number>>(new Map())
  const lastFetchErrorRef = useRef<string | null>(null)
  const metricsEventsCount = activeTab === 'errors' ? ERROR_EVENTS_FETCH_COUNT : 1

  const {
    ready,
    workers,
    resources,
    metrics,
    history,
    error,
    refresh,
  } = useDashboardData(metricsEventsCount)

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

  const rows = useMemo(() => toStatsRows(metrics, statsScope), [metrics, statsScope])

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
      if (!isHttpMetric(metric)) {
        return total
      }
      return total + metric.aggregate.rps
    }, 0)
  }, [metrics])

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

  const availableMetricIds = useMemo(() => {
    const ids = new Set<string>()
    if (metrics) {
      for (const metric of metrics.metrics) {
        ids.add(metric.metric_id)
      }
    }
    for (const point of history) {
      for (const metricId of Object.keys(point.rpsByMetric)) {
        ids.add(metricId)
      }
    }
    return Array.from(ids)
  }, [history, metrics])

  const userCountOptions = useMemo(() => {
    const values = Array.from(new Set(history.map((point) => point.totalUsers)))
      .filter((value) => value >= 0)
      .sort((a, b) => a - b)
    return values.slice(-12)
  }, [history])

  const latencyLineDefs = useMemo(() => {
    return latencySeriesMeta
      .filter((meta) => latencySeriesSelection[meta.id].enabled)
      .map((meta) => {
        const users = latencySeriesSelection[meta.id].users
        const key = `${meta.id}::${users}`
        const label = users === 'all' ? meta.label : `${meta.label} @ ${users} users`
        return {
          ...meta,
          users,
          key,
          label,
        }
      })
  }, [latencySeriesSelection])

  const rpsChartData = useMemo(() => {
    if (history.length === 0 || selectedRpsMetrics.length === 0) {
      return []
    }
    return history.map((point) => {
      const row: Record<string, number | string | null> = {
        time: formatChartTime(point.ts),
      }
      for (const metricId of selectedRpsMetrics) {
        row[metricId] = point.rpsByMetric[metricId] ?? null
      }
      return row
    })
  }, [history, selectedRpsMetrics])

  const latencyChartData = useMemo(() => {
    if (history.length === 0 || latencyLineDefs.length === 0) {
      return []
    }

    return history.map((point) => {
      const row: Record<string, number | string | null> = {
        time: formatChartTime(point.ts),
      }

      for (const line of latencyLineDefs) {
        if (line.users === 'all') {
          row[line.key] = point.latencyByType[line.id]
          continue
        }

        const targetUsers = Number(line.users)
        const tolerance = Math.max(5, Math.round(targetUsers * 0.05))
        if (Math.abs(point.totalUsers - targetUsers) <= tolerance) {
          row[line.key] = point.latencyByType[line.id]
        } else {
          row[line.key] = null
        }
      }

      return row
    })
  }, [history, latencyLineDefs])

  const canStop = ready?.state === 'RUNNING' || ready?.state === 'PREPARING'
  const canStart = ready?.state === 'IDLE'
  const canChangeUsers = ready?.state === 'RUNNING'
  const resourceNames = useMemo(
    () => (resources?.resources ?? []).map((resource) => resource.resource_name),
    [resources],
  )
  const selectedResourceName = useMemo(() => {
    if (resourceNames.includes(resourceNameInput)) {
      return resourceNameInput
    }
    return resourceNames[0] ?? ''
  }, [resourceNameInput, resourceNames])
  const existingResourcesLabel = useMemo(() => {
    if (!resources || resources.resources.length === 0) {
      return null
    }
    return resources.resources.map((resource) => resource.resource_name).join(', ')
  }, [resources])

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
  }, [])

  const toggleErrorsCategoryMenu = useCallback(() => {
    setErrorsCategoryOpen((current) => !current)
    setColumnsOpen(false)
    setSourcesOpen(false)
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

  const toggleLatencySeries = useCallback((seriesId: LatencySeriesId) => {
    setLatencySeriesSelection((current) => {
      const enabledCount = latencySeriesMeta.filter((meta) => current[meta.id].enabled).length
      if (current[seriesId].enabled && enabledCount <= 1) {
        return current
      }
      return {
        ...current,
        [seriesId]: {
          ...current[seriesId],
          enabled: !current[seriesId].enabled,
        },
      }
    })
  }, [])

  const setLatencyUsers = useCallback((seriesId: LatencySeriesId, users: string) => {
    setLatencySeriesSelection((current) => ({
      ...current,
      [seriesId]: {
        ...current[seriesId],
        users,
      },
    }))
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
    if (!columnsOpen && !sourcesOpen && !errorsCategoryOpen) {
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
    }

    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [columnsOpen, errorsCategoryOpen, sourcesOpen])

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
      return availableMetricIds.slice(0, Math.min(3, availableMetricIds.length))
    })
  }, [availableMetricIds, rpsSelectionTouched])

  useEffect(() => {
    if (userCountOptions.length === 0) {
      return
    }

    setLatencySeriesSelection((current) => {
      let changed = false
      const next = { ...current }
      for (const meta of latencySeriesMeta) {
        const selectedUsers = current[meta.id].users
        if (selectedUsers !== 'all' && !userCountOptions.includes(Number(selectedUsers))) {
          next[meta.id] = { ...next[meta.id], users: 'all' }
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [userCountOptions])

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
                    rows.map((row) => (
                      <tr key={row.name}>
                        {visibleColumns.includes('name') ? (
                          <td className={row.isNested ? 'stats-name-cell stats-name-cell--nested' : 'stats-name-cell'}>
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
                          <td>{(row.failureRate * 100).toFixed(2)}%</td>
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
                            <p className="errors-traceback-meta">
                              {[row.errorType, row.errorMessage].filter(Boolean).join(': ')}
                            </p>
                          ) : null}
                          <pre className="errors-traceback-content">{row.traceback}</pre>
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
            </section>

            <section className="chart-grid">
              <article className="chart-card">
                <header className="chart-card__header">
                  <h2>Requests Per Second (RPS)</h2>
                  <div className="chart-card__actions">
                    <button
                      className="btn btn--ghost"
                      type="button"
                      onClick={() => {
                        setRpsSelectionTouched(true)
                        setSelectedRpsMetrics(availableMetricIds)
                      }}
                    >
                      Select all
                    </button>
                    <button
                      className="btn btn--ghost"
                      type="button"
                      onClick={() => {
                        setRpsSelectionTouched(true)
                        setSelectedRpsMetrics([])
                      }}
                    >
                      Clear
                    </button>
                  </div>
                </header>

                <div className="chart-filter-list">
                  {availableMetricIds.length === 0 ? (
                    <p className="chart-empty">No endpoints in metrics stream yet.</p>
                  ) : (
                    availableMetricIds.map((metricId) => (
                      <label className="chart-filter-chip" key={metricId}>
                        <input
                          type="checkbox"
                          checked={selectedRpsMetrics.includes(metricId)}
                          onChange={() => toggleRpsMetric(metricId)}
                        />
                        <span>{metricId}</span>
                      </label>
                    ))
                  )}
                </div>

                <div className="chart-canvas">
                  {rpsChartData.length === 0 || selectedRpsMetrics.length === 0 ? (
                    <p className="chart-empty">Select endpoints to render RPS chart.</p>
                  ) : (
                    <ResponsiveContainer width="100%" height={290}>
                      <LineChart data={rpsChartData}>
                        <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" />
                        <XAxis dataKey="time" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        <Tooltip
                          contentStyle={{
                            borderRadius: 8,
                            border: '1px solid #e2e8f0',
                            fontSize: 12,
                          }}
                          formatter={(value) => {
                            const numeric = typeof value === 'number' ? value : Number(value)
                            if (!Number.isFinite(numeric)) {
                              return '—'
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
                            name={metricId}
                            stroke={rpsLinePalette[index % rpsLinePalette.length]}
                            strokeWidth={2}
                            dot={false}
                            connectNulls
                          />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </article>

              <article className="chart-card">
                <header className="chart-card__header">
                  <h2>Latency (ms)</h2>
                </header>

                <div className="latency-controls">
                  {latencySeriesMeta.map((series) => (
                    <div className="latency-controls__row" key={series.id}>
                      <label className="chart-filter-chip chart-filter-chip--latency">
                        <input
                          type="checkbox"
                          checked={latencySeriesSelection[series.id].enabled}
                          onChange={() => toggleLatencySeries(series.id)}
                        />
                        <span>{series.label}</span>
                      </label>

                      <select
                        className="latency-users-select"
                        value={latencySeriesSelection[series.id].users}
                        onChange={(event) => setLatencyUsers(series.id, event.target.value)}
                        disabled={!latencySeriesSelection[series.id].enabled}
                      >
                        <option value="all">All users</option>
                        {userCountOptions.map((usersCount) => (
                          <option value={String(usersCount)} key={usersCount}>
                            {numberFormatter.format(usersCount)} users
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>

                <div className="chart-canvas">
                  {latencyChartData.length === 0 || latencyLineDefs.length === 0 ? (
                    <p className="chart-empty">Enable latency series to render chart.</p>
                  ) : (
                    <ResponsiveContainer width="100%" height={290}>
                      <LineChart data={latencyChartData}>
                        <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" />
                        <XAxis dataKey="time" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        <Tooltip
                          contentStyle={{
                            borderRadius: 8,
                            border: '1px solid #e2e8f0',
                            fontSize: 12,
                          }}
                          formatter={(value) => {
                            const numeric = typeof value === 'number' ? value : Number(value)
                            if (!Number.isFinite(numeric)) {
                              return '—'
                            }
                            return `${numeric.toFixed(1)} ms`
                          }}
                        />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        {latencyLineDefs.map((line) => (
                          <Line
                            key={line.key}
                            type="monotone"
                            dataKey={line.key}
                            name={line.label}
                            stroke={line.color}
                            strokeWidth={2}
                            dot={false}
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
        selectedResourceName={selectedResourceName}
        countValue={resourceCountInput}
        creating={creatingResource}
        existingResourcesLabel={existingResourcesLabel}
        onClose={() => setResourceModalOpen(false)}
        onResourceChange={setResourceNameInput}
        onCountChange={setResourceCountInput}
        onCreate={onCreateResource}
      />
    </div>
  )
}
