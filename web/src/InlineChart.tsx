import type { Result } from './types'

type Point = { label: string; value: number }

// Trend answers (#6) are expected to carry `result.series`; anything else shows no chart.
export function seriesFrom(result: Result | null | undefined): Point[] | null {
  if (!result || !Array.isArray(result.series) || result.series.length < 2) return null
  return result.series.map((p) => ({ label: String(p.label ?? p.period ?? ''), value: Number(p.value) }))
}

export function InlineChart({ points, format }: { points: Point[]; format: (v: number) => string }) {
  const width = 320
  const height = 96
  const pad = { x: 4, top: 10, bottom: 18 }
  const values = points.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const x = (i: number) => pad.x + (i / (points.length - 1)) * (width - pad.x * 2)
  const y = (v: number) => pad.top + (1 - (v - min) / span) * (height - pad.top - pad.bottom)
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  const area = `${line} L${x(points.length - 1).toFixed(1)},${height - pad.bottom} L${x(0).toFixed(1)},${height - pad.bottom} Z`
  const last = points[points.length - 1]
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${points[0].label} ${format(points[0].value)} to ${last.label} ${format(last.value)}`}>
        <path d={area} className="chart-area" />
        <path d={line} className="chart-line" />
        <circle cx={x(points.length - 1)} cy={y(last.value)} r="3" className="chart-dot" />
        <text x={pad.x} y={height - 4} className="chart-axis">{points[0].label}</text>
        <text x={width - pad.x} y={height - 4} className="chart-axis" textAnchor="end">{last.label}</text>
      </svg>
    </figure>
  )
}
