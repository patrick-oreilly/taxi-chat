import { useEffect, useState } from 'react'

import { CityMap } from './CityMap'
import { Conversation } from './Conversation'
import { Readout } from './Readout'
import { TracePanel } from './TracePanel'
import { useAsk } from './useAsk'

type Stats = { trips: number; months_loaded: number; months_expected: number; complete: boolean }

function Masthead({ stats }: { stats: Stats | null }) {
  return (
    <header className="masthead">
      <h1 className="wordmark">
        <span className="roof-light" aria-hidden />
        Taxi Chat
      </h1>
      <p className="count">
        <span className="num count-value">{stats ? stats.trips.toLocaleString('en-US') : '—'}</span>
        <span className="count-label">
          NYC trips, Jan 2019 – Dec 2025
          {stats && !stats.complete && ` · ${stats.months_loaded} of ${stats.months_expected} months loaded`}
        </span>
      </p>
    </header>
  )
}

export default function App() {
  const { turns, ask } = useAsk()
  const [stats, setStats] = useState<Stats | null>(null)

  useEffect(() => {
    fetch('/api/stats').then((r) => r.json()).then(setStats).catch(() => setStats(null))
  }, [])

  const active = turns[turns.length - 1]
  const busy = active?.status === 'streaming'
  const lastFinished = [...turns].reverse().find((t) => t.status !== 'streaming')
  const declined = !busy && (active?.status === 'declined' || active?.status === 'error')
  const queried = active?.events.find((e) => e.stage === 'queried')
  const querying = busy && !!active?.events.find((e) => e.stage === 'resolved') && !queried

  return (
    <div className={`app${busy ? ' is-busy' : ''}`}>
      <CityMap highlight={busy ? undefined : lastFinished?.highlight} declined={declined} busy={busy} />
      {declined && active?.declineMessage && (
        <div className="decline-banner" role="status">
          <span className="answer-tag">{active.status === 'declined' ? 'Declined' : 'Error'}</span>
          {active.declineMessage}
        </div>
      )}
      <Conversation turns={turns} onAsk={ask} busy={busy} header={<Masthead stats={stats} />} />
      <TracePanel turn={active} />
      {(queried || querying) && (
        <Readout
          rows={(queried?.rows_scanned as number) ?? 0}
          source={(queried?.source as string) ?? null}
          ms={active?.trace?.timings_ms?.query ?? null}
          pending={querying}
        />
      )}
    </div>
  )
}
