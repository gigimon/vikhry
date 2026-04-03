import {
  Clock3,
  RefreshCcw,
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
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlightRef.current) {
      return
    }

    inFlightRef.current = true
    setRefreshing(true)

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
    setRefreshing(false)
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
    refreshing,
    error,
    refresh,
  }
}

export function ProbeChartsPanel() {
  const { ready, probes, loading, refreshing, error, refresh } = useProbeDashboardData()

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

  return (
    <div className="probe-content">
      <section className="section-header probe-page__header">
        <div>
          <h1>Probe Timeline</h1>
          <p className="probe-page__subtitle">
            One chart per probe. Numeric probes render their values; non-numeric probes fall back to a status line.
          </p>
        </div>
        <div className="probe-page__header-side">
          <div className="probe-page__meta">
            <span className="probe-page__meta-item">
              <Clock3 size={13} />
              <span>
                State {ready?.state ?? 'Unknown'} • Updated{' '}
                {probes
                  ? new Date(probes.generated_at * 1000).toLocaleTimeString('en-US', { hour12: false })
                  : '—'}
              </span>
            </span>
            {probes?.lag.detected ? (
              <span className="probe-page__meta-item probe-page__meta-item--warning">
                <TriangleAlert size={13} />
                <span>Backlog: {probes.lag.probes_with_backlog.join(', ')}</span>
              </span>
            ) : null}
          </div>
          <button
            className="btn btn--primary has-tooltip"
            type="button"
            onClick={() => void refresh()}
            data-tooltip={refreshing ? 'Refreshing probes...' : 'Refresh probe charts'}
          >
            <RefreshCcw size={12} />
            <span>{refreshing ? 'Refreshing...' : 'Refresh'}</span>
          </button>
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
          {cards.map((card) => (
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
                  <p className="probe-chart-card__caption">
                    Latest update: {formatProbeTimestamp(card.latest?.ts_ms ?? null)}
                  </p>
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

              {card.points.length === 0 ? (
                <p className="chart-empty">No probe events collected yet.</p>
              ) : (
                <div className="chart-canvas probe-chart-canvas">
                  <ResponsiveContainer width="100%" height={260}>
                    <LineChart data={card.points} margin={{ top: 12, right: 16, left: 4, bottom: 8 }}>
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
              ) : (
                <footer className="probe-chart-card__footer">Window: {card.aggregate.window_s}s</footer>
              )}
            </article>
          ))}
        </section>
      )}
    </div>
  )
}
