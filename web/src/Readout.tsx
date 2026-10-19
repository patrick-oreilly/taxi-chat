import { useEffect, useRef, useState } from 'react'

// Counts from the last shown value to the new one with an exponential ease-out.
function useCountUp(target: number, duration = 1100) {
  const [shown, setShown] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    const start = performance.now()
    const begin = from.current
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setShown(target); from.current = target; return }
    let frame = 0
    const tick = (now: number) => {
      const x = Math.min(1, (now - start) / duration)
      const eased = x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)
      const value = begin + (target - begin) * eased
      setShown(value)
      from.current = value
      if (x < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, duration])
  return shown
}

// Queries report once they finish, so while one runs the readout says so; a
// raw-trip scan then counts up slower, so tens of millions of rows read as such.
export function Readout({ rows, source, ms, pending }: { rows: number; source: string | null; ms: number | null; pending: boolean }) {
  const shown = useCountUp(rows, source === 'raw' ? 2400 : 1100)
  if (pending) {
    return (
      <div className="readout is-pending" aria-live="off">
        <span className="readout-label">running the query…</span>
      </div>
    )
  }
  return (
    <div className={`readout${source === 'raw' ? ' is-raw' : ''}`} aria-live="off">
      <span className="readout-value num">{Math.round(shown).toLocaleString('en-US')}</span>
      <span className="readout-label">
        rows scanned{source ? ` from ${source === 'raw' ? 'raw trips' : 'hourly rollups'}` : ''}
        {ms != null && <span className="mono"> · {ms.toFixed(0)} ms</span>}
      </span>
    </div>
  )
}
