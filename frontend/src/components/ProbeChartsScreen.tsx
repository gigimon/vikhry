import {
  ChevronDown,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { fetchProbes, fetchReady } from '../api/dashboardApi'
import type { ProbeScalar, ProbesResponse, ReadyResponse } from '../types/dashboard'

const PROBE_REFRESH_INTERVAL_MS = 1_000
const PROBE_HISTORY_COUNT = 240

type ProbeChartMode = 'value' | 'boolean' | 'status'
type ProbeRangeId = '5m' | '15m' | '30m' | 'all'

const probeRanges: Array<{ id: ProbeRangeId; label: string }> = [
  { id: '5m', label: '5 minutes' },
  { id: '15m', label: '15 minutes' },
  { id: '30m', label: '30 minutes' },
  { id: 'all', label: 'All time' },
]
const probeRangeToMs: Record<Exclude<ProbeRangeId, 'all'>, number> = {
  '5m': 5 * 60 * 1000,
  '15m': 15 * 60 * 1000,
  '30m': 30 * 60 * 1000,
}

interface ProbeChartPoint {
  tsMs: number
  time: string
  value: number | null
  statusLabel: 'OK' | 'ERR'
  rawValue: ProbeScalar
  rawValueLabel: string
  elapsedMs: number | null
}

interface ProbeCardViewModel {
  probeName: string
  aggregate: ProbesResponse['probes'][number]['aggregate']
  latest: ProbesResponse['probes'][number]['latest']
  points: ProbeChartPoint[]
  chartMode: ProbeChartMode
  chartLabel: string
  latestValueLabel: string
}

const numberFormatter = new Intl.NumberFormat('en-US')
const compactNumberFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 2,
})

function formatProbeValue(value: ProbeScalar): string {
  if (value === null) {
    return '—'
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false'
  }
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? numberFormatter.format(value)
      : compactNumberFormatter.format(value)
  }
  return value
}

function formatProbeTimestamp(value: number | null): string {
  if (value === null) {
    return 'No data yet'
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

function formatChartTime(value: number): string {
  return new Date(value).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function parseProbeEventTimestampMs(eventId: string, data: Record<string, unknown>): number | null {
  const rawTsMs = data.ts_ms
  if (typeof rawTsMs === 'number' && Number.isFinite(rawTsMs)) {
    return rawTsMs
  }
  const parsedHead = Number.parseInt(eventId.split('-', 1)[0] ?? '', 10)
  return Number.isFinite(parsedHead) && parsedHead > 0 ? parsedHead : null
}

function deriveProbeChartMode(
  events: NonNullable<ProbesResponse['probes'][number]['events']>,
): ProbeChartMode {
  for (const event of events) {
    const value = event.data.value
    if (typeof value === 'number' && Number.isFinite(value)) {
      return 'value'
    }
  }
  for (const event of events) {
    if (typeof event.data.value === 'boolean') {
      return 'boolean'
    }
  }
  return 'status'
}

function buildProbeCardViewModel(
  probe: ProbesResponse['probes'][number],
): ProbeCardViewModel {
  const events = probe.events ?? []
  const chartMode = deriveProbeChartMode(events)
  const points = events
    .map((event) => {
      const data = event.data
      const tsMs = parseProbeEventTimestampMs(event.event_id, data)
      if (tsMs === null) {
        return null
      }

      const rawValue = (data.value as ProbeScalar | undefined) ?? null
      let value: number | null
      if (chartMode === 'value') {
        value = typeof rawValue === 'number' && Number.isFinite(rawValue) ? rawValue : null
      } else if (chartMode === 'boolean') {
        value = typeof rawValue === 'boolean' ? (rawValue ? 1 : 0) : null
      } else {
        value = data.status === true ? 1 : 0
      }

      return {
        tsMs,
        time: formatChartTime(tsMs),
        value,
        statusLabel: data.status === true ? 'OK' : 'ERR',
        rawValue,
        rawValueLabel: formatProbeValue(rawValue),
        elapsedMs:
          typeof data.time === 'number' && Number.isFinite(data.time) ? data.time : null,
      } satisfies ProbeChartPoint
    })
    .filter((point): point is ProbeChartPoint => point !== null)

  return {
    probeName: probe.probe_name,
    aggregate: probe.aggregate,
    latest: probe.latest,
    points,
    chartMode,
    chartLabel:
      chartMode === 'value'
        ? 'Probe value'
        : chartMode === 'boolean'
          ? 'Boolean value'
          : 'Probe status',
    latestValueLabel: formatProbeValue(probe.aggregate.last_value),
  }
}

function probeStatusTone(latest: ProbesResponse['probes'][number]['latest']): string {
  if (latest?.status === true) {
    return 'probe-pill--healthy'
  }
  if (latest?.status === false) {
    return 'probe-pill--failing'
  }
  return 'probe-pill--idle'
}

function probeStatusLabel(latest: ProbesResponse['probes'][number]['latest']): string {
  if (latest?.status === true) {
    return 'Healthy'
  }
  if (latest?.status === false) {
    return 'Failing'
  }
  return 'No data'
}

function useProbeDashboardData() {
  const [ready, setReady] = useState<ReadyResponse | null>(null)
  const [probes, setProbes] = useState<ProbesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlightRef.current) {
      return
    }

    inFlightRef.current = true

    const [readyResult, probesResult] = await Promise.allSettled([
      fetchReady(),
      fetchProbes({
        count: PROBE_HISTORY_COUNT,
        includeEvents: true,
      }),
    ])

    const errors: string[] = []

    if (readyResult.status === 'fulfilled') {
      setReady(readyResult.value)
    } else {
      setReady(null)
      errors.push(readyResult.reason instanceof Error ? readyResult.reason.message : 'ready failed')
    }

    if (probesResult.status === 'fulfilled') {
      setProbes(probesResult.value)
    } else {
      setProbes(null)
      errors.push(probesResult.reason instanceof Error ? probesResult.reason.message : 'probes failed')
    }

    setError(errors.length > 0 ? Array.from(new Set(errors)).join(' | ') : null)
    setLoading(false)
    inFlightRef.current = false
  }, [])

  useEffect(() => {
    const initialTimerId = window.setTimeout(() => {
      void refresh()
    }, 0)
    const timerId = window.setInterval(() => {
      void refresh()
    }, PROBE_REFRESH_INTERVAL_MS)

    return () => {
      window.clearTimeout(initialTimerId)
      window.clearInterval(timerId)
    }
  }, [refresh])

  return {
    ready,
    probes,
    loading,
    error,
    refresh,
  }
}

function filterPointsByRange(points: ProbeChartPoint[], rangeId: ProbeRangeId): ProbeChartPoint[] {
  if (rangeId === 'all') {
    return points
  }
  const windowMs = probeRangeToMs[rangeId]
  const cutoff = Date.now() - windowMs
  return points.filter((p) => p.tsMs >= cutoff)
}

export function ProbeChartsPanel() {
  const { probes, loading, error } = useProbeDashboardData()
  const [selectedRange, setSelectedRange] = useState<ProbeRangeId>('all')
  const [rangeOpen, setRangeOpen] = useState(false)
  const rangeContainerRef = useRef<HTMLDivElement | null>(null)

  const cards = useMemo(() => {
    if (!probes) {
      return []
    }
    return probes.probes.map(buildProbeCardViewModel)
  }, [probes])

  const summary = useMemo(() => {
    const total = cards.length
    const healthy = cards.filter((card) => card.latest?.status === true).length
    const failing = cards.filter((card) => card.latest?.status === false).length
    const idle = total - healthy - failing
    return { total, healthy, failing, idle }
  }, [cards])

  const selectedRangeLabel = useMemo(() => {
    return probeRanges.find((r) => r.id === selectedRange)?.label ?? 'All time'
  }, [selectedRange])

  const toggleRangeMenu = useCallback(() => {
    setRangeOpen((prev) => !prev)
  }, [])

  const selectRange = useCallback((id: ProbeRangeId) => {
    setSelectedRange(id)
    setRangeOpen(false)
  }, [])

  // Close dropdown on outside click
  useEffect(() => {
    if (!rangeOpen) return
    const onPointerDown = (e: PointerEvent) => {
      if (rangeContainerRef.current && !rangeContainerRef.current.contains(e.target as Node)) {
        setRangeOpen(false)
      }
    }
    window.addEventListener('pointerdown', onPointerDown)
    return () => window.removeEventListener('pointerdown', onPointerDown)
  }, [rangeOpen])

  return (
    <div className="probe-content">
      <section className="section-header probe-page__header">
        <h1>Probe Timeline</h1>
        <div className="probe-page__header-side">
          {probes?.lag.detected ? (
            <span className="probe-page__meta-item probe-page__meta-item--warning">
              <TriangleAlert size={13} />
              <span>Backlog: {probes.lag.probes_with_backlog.join(', ')}</span>
            </span>
          ) : null}
          <div className="columns-control" ref={rangeContainerRef}>
            <button className="btn" type="button" onClick={toggleRangeMenu}>
              <span>{selectedRangeLabel}</span>
              <ChevronDown size={12} />
            </button>
            {rangeOpen ? (
              <div className="columns-menu">
                {probeRanges.map((range) => (
                  <button
                    key={range.id}
                    type="button"
                    className={
                      selectedRange === range.id
                        ? 'columns-menu__option columns-menu__option--active'
                        : 'columns-menu__option'
                    }
                    onClick={() => selectRange(range.id)}
                  >
                    {range.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      {error ? <section className="probe-banner probe-banner--error">{error}</section> : null}

      <section className="probe-summary-grid">
        <article className="probe-summary-card">
          <p className="probe-summary-card__label">Total probes</p>
          <p className="probe-summary-card__value">{numberFormatter.format(summary.total)}</p>
        </article>
        <article className="probe-summary-card">
          <p className="probe-summary-card__label">Healthy</p>
          <p className="probe-summary-card__value">{numberFormatter.format(summary.healthy)}</p>
        </article>
        <article className="probe-summary-card probe-summary-card--danger">
          <p className="probe-summary-card__label">Failing</p>
          <p className="probe-summary-card__value">{numberFormatter.format(summary.failing)}</p>
        </article>
        <article className="probe-summary-card">
          <p className="probe-summary-card__label">No data</p>
          <p className="probe-summary-card__value">{numberFormatter.format(summary.idle)}</p>
        </article>
      </section>

      {loading ? (
        <section className="chart-card">
          <p className="chart-empty">Loading probe charts...</p>
        </section>
      ) : cards.length === 0 ? (
        <section className="chart-card probe-empty-card">
          <p className="probe-empty-card__title">No probe data yet</p>
          <p className="probe-empty-card__body">
            Declare probes in the scenario and start at least one worker with <code>--run-probes</code>.
          </p>
        </section>
      ) : (
        <section className="probe-chart-list">
          {cards.map((card) => {
            const visiblePoints = filterPointsByRange(card.points, selectedRange)
            return (
              <article key={card.probeName} className="chart-card probe-chart-card">
                <header className="chart-card__header probe-chart-card__header">
                  <div className="probe-chart-card__title-block">
                    <div className="probe-chart-card__title-row">
                      <h2>{card.probeName}</h2>
                      <span className={`probe-pill ${probeStatusTone(card.latest)}`}>
                        {probeStatusLabel(card.latest)}
                      </span>
                      <span className="probe-pill probe-pill--neutral">{card.chartLabel}</span>
                    </div>
                  </div>

                  <div className="probe-chart-card__stats">
                    <div className="probe-stat">
                      <span className="probe-stat__label">Latest</span>
                      <strong className="probe-stat__value">{card.latestValueLabel}</strong>
                    </div>
                    <div className="probe-stat">
                      <span className="probe-stat__label">Successes</span>
                      <strong className="probe-stat__value">{numberFormatter.format(card.aggregate.successes)}</strong>
                    </div>
                    <div className="probe-stat">
                      <span className="probe-stat__label">Errors</span>
                      <strong className="probe-stat__value">{numberFormatter.format(card.aggregate.errors)}</strong>
                    </div>
                  </div>
                </header>

                {visiblePoints.length === 0 ? (
                  <p className="chart-empty">No probe events in selected range.</p>
                ) : (
                  <div className="chart-canvas probe-chart-canvas">
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart data={visiblePoints} margin={{ top: 12, right: 16, left: 4, bottom: 8 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#dbe4ec" />
                        <XAxis dataKey="time" minTickGap={24} stroke="#64748b" />
                        <YAxis
                          stroke="#64748b"
                          domain={card.chartMode === 'value' ? ['auto', 'auto'] : [0, 1]}
                          ticks={card.chartMode === 'value' ? undefined : [0, 1]}
                          tickFormatter={(value: number) => {
                            if (card.chartMode === 'value') {
                              return compactNumberFormatter.format(value)
                            }
                            return value === 1 ? 'OK' : 'ERR'
                          }}
                          width={56}
                        />
                        <Tooltip
                          formatter={(_value, _name, item) => {
                            const payload = item.payload as ProbeChartPoint
                            if (card.chartMode === 'status') {
                              return [payload.statusLabel, 'Status']
                            }
                            return [payload.rawValueLabel, 'Value']
                          }}
                          labelFormatter={(_label, items) => {
                            const payload = items[0]?.payload as ProbeChartPoint | undefined
                            if (!payload) {
                              return '—'
                            }
                            const elapsed = payload.elapsedMs === null ? '—' : `${payload.elapsedMs.toFixed(2)} ms`
                            return `${formatProbeTimestamp(payload.tsMs)} | ${elapsed}`
                          }}
                        />
                        <Line
                          type="monotone"
                          dataKey="value"
                          stroke={card.latest?.status === false ? '#ef4444' : '#0891b2'}
                          strokeWidth={2.5}
                          dot={false}
                          isAnimationActive={false}
                          connectNulls
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {card.latest?.error_message ? (
                  <footer className="probe-chart-card__footer probe-chart-card__footer--error">
                    <strong>{card.latest.error_type ?? 'ProbeError'}:</strong> {card.latest.error_message}
                  </footer>
                ) : null}
              </article>
            )
          })}
        </section>
      )}
    </div>
  )
}
