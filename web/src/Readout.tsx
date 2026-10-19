import { useEffect, useRef, useState } from 'react'

// Counts from the last shown value to the new one with an exponential ease-out.
export function useCountUp(target: number, duration = 1100) {
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

export function Readout({ rows, source, ms }: { rows: number; source: string | null; ms: number | null }) {
  const shown = useCountUp(rows)
  return (
    <div className="readout" aria-live="off">
      <span className="readout-value num">{Math.round(shown).toLocaleString('en-US')}</span>
      <span className="readout-label">
        rows scanned{source ? ` from ${source === 'raw' ? 'raw trips' : 'hourly rollups'}` : ''}
        {ms != null && <span className="mono"> · {ms.toFixed(0)} ms</span>}
      </span>
    </div>
  )
}
