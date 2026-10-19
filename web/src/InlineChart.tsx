import type { Derived, Result } from './types'

type Format = (v: number) => string

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function stepLabel(t: string, grain: Result['grain']) {
  const [y, m, d] = t.split('-').map(Number)
  if (grain === 'year') return String(y)
  if (grain === 'month') return `${MONTHS[m - 1]} ${y}`
  return `${d} ${MONTHS[m - 1]}`
}

// Steps cut off by the period's edges (complete: false) aren't comparable with
// full ones, so they're drawn hollow on a dashed line rather than hidden.
export function TrendChart({ result, format }: { result: Result; format: Format }) {
  const points = (result.series ?? []).filter((p) => p.value != null) as { t: string; value: number; complete: boolean }[]
  if (points.length < 2) return null
  const width = 360
  const height = 118
  const pad = { x: 6, top: 22, bottom: 20 }
  const values = points.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const x = (i: number) => pad.x + (i / (points.length - 1)) * (width - pad.x * 2)
  const y = (v: number) => pad.top + (1 - (v - min) / span) * (height - pad.top - pad.bottom)
  const segments = points.slice(1).map((p, i) => ({
    d: `M${x(i).toFixed(1)},${y(points[i].value).toFixed(1)} L${x(i + 1).toFixed(1)},${y(p.value).toFixed(1)}`,
    partial: !p.complete || !points[i].complete,
  }))
  const complete = points.map((p, i) => ({ ...p, i })).filter((p) => p.complete)
  const area = complete.length > 1
    ? `M${x(complete[0].i)},${height - pad.bottom} ` + complete.map((p) => `L${x(p.i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ') + ` L${x(complete[complete.length - 1].i)},${height - pad.bottom} Z`
    : ''
  const peak = complete.reduce((best, p) => (p.value > best.value ? p : best), complete[0] ?? { ...points[0], i: 0 })
  const first = points[0]
  const last = points[points.length - 1]
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`From ${stepLabel(first.t, result.grain)} to ${stepLabel(last.t, result.grain)}, peaking at ${format(peak.value)}`}>
        {area && <path d={area} className="chart-area" />}
        {segments.map((s, i) => <path key={i} d={s.d} className={`chart-line${s.partial ? ' is-partial' : ''}`} />)}
        {points.map((p, i) => <circle key={p.t} cx={x(i)} cy={y(p.value)} r={p.complete ? 2.4 : 2.6} className={`chart-dot${p.complete ? '' : ' is-partial'}`} />)}
        <text x={x(peak.i)} y={y(peak.value) - 9} className="chart-peak" textAnchor={peak.i > points.length * 0.75 ? 'end' : peak.i < points.length * 0.25 ? 'start' : 'middle'}>
          {format(peak.value)}
        </text>
        <text x={pad.x} y={height - 4} className="chart-axis">{stepLabel(first.t, result.grain)}</text>
        <text x={width - pad.x} y={height - 4} className="chart-axis" textAnchor="end">{stepLabel(last.t, result.grain)}</text>
      </svg>
      {points.some((p) => !p.complete) && <figcaption>Hollow points are partial {result.grain}s at the edges of the period.</figcaption>}
    </figure>
  )
}

export function CompareBars({ result, derived, format }: { result: Result; derived?: Derived | null; format: Format }) {
  const groups = result.groups ?? []
  const max = Math.max(...groups.map((g) => g.value ?? 0), 0)
  if (groups.length < 2 || max <= 0) return null
  return (
    <figure className="compare">
      {groups.map((g, i) => (
        <div key={g.label} className={`compare-row is-${i ? 'b' : 'a'}`}>
          <span className="compare-label">{g.label}</span>
          <span className="compare-track"><span className="compare-bar" style={{ width: `${((g.value ?? 0) / max) * 100}%` }} /></span>
          <span className="num compare-value">{g.value == null ? '—' : format(g.value)}</span>
        </div>
      ))}
      {typeof derived?.ratio === 'number' && (
        <figcaption>
          <span className="num">{derived.ratio.toFixed(2)}×</span>
          {typeof derived.pct_difference === 'number' && <span className="num"> · {derived.pct_difference > 0 ? '+' : ''}{derived.pct_difference.toFixed(1)}%</span>}
        </figcaption>
      )}
    </figure>
  )
}

function bucketLabel(from: number | null, to: number | null) {
  const n = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1))
  if (from == null && to != null) return `<${n(to)}`
  if (to == null && from != null) return `≥${n(from)}`
  return `${n(from!)}–${n(to!)}`
}

export function Histogram({ result }: { result: Result }) {
  const buckets = result.buckets ?? []
  const max = Math.max(...buckets.map((b) => b.share ?? 0), 0)
  if (!buckets.length || max <= 0) return null
  const lit = (b: (typeof buckets)[number]) => result.threshold != null && b.to != null && b.to <= result.threshold
  return (
    <figure className="histogram">
      <div className="bars">
        {buckets.map((b, i) => (
          <div key={i} className={`bar${lit(b) ? ' is-lit' : ''}`} title={`${b.trips.toLocaleString('en-US')} trips`}>
            <span className="num bar-share">{b.share == null ? '' : `${Math.round(b.share * 100)}%`}</span>
            <span className="bar-fill" style={{ height: `${((b.share ?? 0) / max) * 100}%` }} />
            <span className="bar-label num">{bucketLabel(b.from, b.to)}</span>
          </div>
        ))}
      </div>
      <figcaption>{result.unit ?? ''} · {(result.trips ?? 0).toLocaleString('en-US')} trips</figcaption>
    </figure>
  )
}
