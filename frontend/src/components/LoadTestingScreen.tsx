import {
  Activity,
  ChevronDown,
  Columns3,
  Gauge,
  Layers,
  Play,
  RefreshCcw,
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
  API_BASE_URL,
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

type TabId = 'statistics' | 'charts' | 'resources' | 'workers'
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

interface ChartHistoryPoint {
  ts: number
  totalUsers: number
  rpsByMetric: Record<string, number>
  latencyByType: Record<LatencySeriesId, number | null>
}

const tabs: Array<{ id: TabId; label: string }> = [
  { id: 'statistics', label: 'Statistics' },
  { id: 'charts', label: 'Charts' },
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

function toStatsRows(metrics: MetricsResponse | null): StatsRow[] {
  if (!metrics) {
    return []
  }

  return metrics.metrics.map((item) => {
    const { aggregate } = item
    const failure = aggregate.errors
    const success = Math.max(0, aggregate.requests - failure)
    return {
      name: item.metric_id,
      success,
      failure,
      medianMs: aggregate.latency_median_ms,
      p95Ms: aggregate.latency_p95_ms,
      p99Ms: aggregate.latency_p99_ms,
      averageMs: aggregate.latency_avg_ms,
      rps: aggregate.rps,
      failureRate: aggregate.error_rate,
    }
  })
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

function buildHistoryPoint(
  metrics: MetricsResponse,
  workers: WorkersResponse,
  generatedAt: number,
): ChartHistoryPoint {
  const totalUsers = workers.workers.reduce((total, worker) => total + worker.users_count, 0)
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

function useDashboardData() {
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
      fetchMetrics(),
    ])

    const errors: string[] = []
    const pushError = (scope: string, reason: unknown) => {
      const message = reason instanceof Error ? reason.message : 'request failed'
      errors.push(`${scope}: ${message}`)
    }

    if (readyResult.status === 'fulfilled') {
      setReady(readyResult.value)
    } else {
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
      const point = buildHistoryPoint(metricsResult.value, workersResult.value, ts)
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
  }, [])

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
  const [visibleColumns, setVisibleColumns] = useState<StatsColumnId[]>(defaultVisibleColumns)
  const [columnsOpen, setColumnsOpen] = useState(false)

  const [startModalOpen, setStartModalOpen] = useState(false)
  const [resourceModalOpen, setResourceModalOpen] = useState(false)

  const [stopping, setStopping] = useState(false)
  const [starting, setStarting] = useState(false)
  const [creatingResource, setCreatingResource] = useState(false)

  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  const [targetUsersInput, setTargetUsersInput] = useState('1000')
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

  const columnsContainerRef = useRef<HTMLDivElement | null>(null)

  const {
    ready,
    workers,
    resources,
    metrics,
    history,
    loading,
    refreshing,
    error,
    refresh,
  } = useDashboardData()

  const rows = useMemo(() => toStatsRows(metrics), [metrics])

  const totalUsers = useMemo(() => {
    if (!workers) {
      return 0
    }
    return workers.workers.reduce((total, worker) => total + worker.users_count, 0)
  }, [workers])

  const totalRps = useMemo(() => {
    if (!metrics) {
      return 0
    }
    return metrics.metrics.reduce((total, metric) => total + metric.aggregate.rps, 0)
  }, [metrics])

  const workerRows = useMemo(() => {
    if (!workers) {
      return []
    }

    return workers.workers.map((worker) => {
      const badge = workerBadge(worker)

      const rawCpu = worker.cpu_percent ?? worker.cpu_load ?? null
      const cpuLoad =
        typeof rawCpu === 'number' && Number.isFinite(rawCpu)
          ? clampPercent(rawCpu)
          : null

      const rawMemory = worker.memory_percent ?? worker.ram_load ?? null
      const ramLoad =
        typeof rawMemory === 'number' && Number.isFinite(rawMemory)
          ? clampPercent(rawMemory)
          : null

      return {
        worker,
        badge,
        cpuLoad,
        ramLoad,
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

  const refreshData = useCallback(async () => {
    setActionMessage(null)
    setActionError(null)
    await refresh()
  }, [refresh])

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
      setActionError(null)
      setActionMessage(null)
      await stopTest()
      setActionMessage('Stop command sent.')
      await refresh()
    } catch (stopError) {
      setActionError(stopError instanceof Error ? stopError.message : 'Failed to stop test')
    } finally {
      setStopping(false)
    }
  }, [refresh])

  const onStart = useCallback(async () => {
    const targetUsers = Number(targetUsersInput)
    if (!Number.isInteger(targetUsers) || targetUsers < 0) {
      setActionError('Users must be an integer >= 0.')
      return
    }

    const initParams: Record<string, unknown> = {}
    if (scenarioSpec) {
      for (const param of scenarioSpec.params) {
        const rawValue = initParamValues[param.name]?.trim() ?? ''
        if (rawValue.length === 0) {
          if (param.required) {
            setActionError(`Init parameter \`${param.name}\` is required.`)
            return
          }
          continue
        }
        initParams[param.name] = parseInputValue(rawValue)
      }
    }

    try {
      setStarting(true)
      setActionError(null)
      setActionMessage(null)
      await startTest({
        target_users: targetUsers,
        init_params: initParams,
      })
      setStartModalOpen(false)
      setActionMessage('Start command sent.')
      await refresh()
    } catch (startError) {
      setActionError(startError instanceof Error ? startError.message : 'Failed to start test')
    } finally {
      setStarting(false)
    }
  }, [initParamValues, refresh, scenarioSpec, targetUsersInput])

  const onCreateResource = useCallback(async () => {
    const name = selectedResourceName.trim()
    const count = Number(resourceCountInput)

    if (!name) {
      setActionError('Resource name is required.')
      return
    }

    if (!Number.isInteger(count) || count < 1) {
      setActionError('Resource count must be an integer >= 1.')
      return
    }

    try {
      setCreatingResource(true)
      setActionError(null)
      setActionMessage(null)
      await createResource({ name, count })
      setResourceModalOpen(false)
      setActionMessage(`Created ${count} resource(s) for ${name}.`)
      await refresh()
    } catch (createError) {
      setActionError(createError instanceof Error ? createError.message : 'Failed to create resources')
    } finally {
      setCreatingResource(false)
    }
  }, [refresh, resourceCountInput, selectedResourceName])

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
    if (!columnsOpen) {
      return
    }

    const onPointerDown = (event: PointerEvent) => {
      if (!columnsContainerRef.current?.contains(event.target as Node)) {
        setColumnsOpen(false)
      }
    }

    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [columnsOpen])

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
        setInitParamValues(() => {
          const initial: Record<string, string> = {}
          for (const param of spec.params) {
            if (param.default === null || param.default === undefined) {
              initial[param.name] = ''
              continue
            }
            if (typeof param.default === 'string') {
              initial[param.name] = param.default
              continue
            }
            initial[param.name] = JSON.stringify(param.default)
          }
          return initial
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
          <div className="pill pill--state">
            <Play size={10} fill="currentColor" />
            <span>{statusLabel(ready?.state)}</span>
          </div>
          <div className="pill">
            <Users size={12} />
            <span>{numberFormatter.format(totalUsers)}</span>
          </div>
          <div className="pill">
            <Gauge size={12} />
            <span>{numberFormatter.format(ready?.alive_workers ?? 0)}</span>
          </div>
          <div className="pill">
            <Activity size={12} />
            <span>{compactNumberFormatter.format(totalRps)} RPS</span>
          </div>
        </div>

        <div className="topbar__actions">
          {canStart ? (
            <button className="btn btn--primary" type="button" onClick={() => setStartModalOpen(true)}>
              <Play size={12} />
              <span>Start</span>
            </button>
          ) : null}
          {canStop ? (
            <button className="btn btn--primary" disabled={stopping} onClick={() => void onStop()} type="button">
              <Square size={12} />
              <span>{stopping ? 'Stopping...' : 'Stop'}</span>
            </button>
          ) : null}
          <button className="btn" type="button" onClick={() => openResourceModal()}>
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
        {actionError ? <div className="status-banner status-banner--error">{actionError}</div> : null}
        {actionMessage ? <div className="status-banner">{actionMessage}</div> : null}
        {error ? <div className="status-banner status-banner--error">Failed to fetch data: {error}</div> : null}
        {!error && loading ? <div className="status-banner">Loading data from {API_BASE_URL} ...</div> : null}

        {activeTab === 'statistics' ? (
          <>
            <section className="section-header">
              <h1>Test Statistics</h1>
              <div className="columns-control" ref={columnsContainerRef}>
                <button className="btn" type="button" onClick={() => setColumnsOpen((current) => !current)}>
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
                      <td colSpan={visibleColumns.length}>No metrics received from /metrics yet.</td>
                    </tr>
                  ) : (
                    rows.map((row) => (
                      <tr key={row.name}>
                        {visibleColumns.includes('name') ? <td>{row.name}</td> : null}
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
          </>
        ) : null}

        {activeTab === 'resources' ? (
          <>
            <section className="section-header">
              <h1>Resources</h1>
              <button className="btn" type="button" onClick={() => void refreshData()} disabled={refreshing}>
                <RefreshCcw size={12} className={refreshing ? 'spin' : undefined} />
                <span>{refreshing ? 'Refreshing...' : 'Refresh'}</span>
              </button>
            </section>

            <section className="table-card resources-table">
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
                      <td colSpan={3}>No resources in orchestrator state (/resources).</td>
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
              <button className="btn" type="button" onClick={() => void refreshData()} disabled={refreshing}>
                <RefreshCcw size={12} className={refreshing ? 'spin' : undefined} />
                <span>{refreshing ? 'Refreshing...' : 'Refresh'}</span>
              </button>
            </section>

            <section className="table-card workers-table">
              <table>
                <thead>
                  <tr>
                    <th>Worker ID</th>
                    <th>Healthcheck</th>
                    <th>Last Seen</th>
                    <th>CPU Load</th>
                    <th>RAM Load</th>
                  </tr>
                </thead>
                <tbody>
                  {workerRows.length === 0 ? (
                    <tr>
                      <td colSpan={5}>No workers in orchestrator state (/workers).</td>
                    </tr>
                  ) : (
                    workerRows.map(({ worker, badge, cpuLoad, ramLoad }) => (
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
                              <span>{ramLoad}%</span>
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
              <button className="btn" type="button" onClick={() => void refreshData()} disabled={refreshing}>
                <RefreshCcw size={12} className={refreshing ? 'spin' : undefined} />
                <span>{refreshing ? 'Refreshing...' : 'Refresh'}</span>
              </button>
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
