import { useEffect, useRef, useState, type FormEvent } from 'react'

import { Icon } from './Icon'
import { InlineChart, seriesFrom } from './InlineChart'
import type { Turn } from './types'

const SUGGESTIONS = [
  'What were the 5 busiest pickup zones in January 2024?',
  'Average Uber fare from JFK in January 2024?',
  'Which borough had the highest average tip for yellow cabs on weekend nights in January 2024?',
  'How many Lyft rides were there in January 2024?',
  'Will fares go up next year?',
]

const PROGRESS: Record<string, string> = {
  classified: 'Resolving dates and places…',
  resolved: 'Running the query…',
  queried: 'Writing the answer…',
  checked: 'Checking every number…',
}

function format(unit: string | undefined, value: number) {
  if (unit === 'usd') return `$${value.toFixed(2)}`
  if (unit === 'miles') return `${value.toFixed(2)} mi`
  if (unit === 'minutes') return `${value.toFixed(1)} min`
  return Math.round(value).toLocaleString('en-US')
}

function Answer({ turn }: { turn: Turn }) {
  const result = turn.trace?.result
  const points = seriesFrom(result)
  if (turn.status === 'streaming') {
    const last = turn.events[turn.events.length - 1]?.stage
    return <p className="answer is-pending">{(last && PROGRESS[last]) || 'Reading the question…'}</p>
  }
  if (turn.status === 'declined' || turn.status === 'error') {
    return (
      <div className={`answer is-${turn.status}`}>
        <span className="answer-tag">{turn.status === 'declined' ? 'Declined' : 'Error'}</span>
        <p>{turn.declineMessage}</p>
      </div>
    )
  }
  return (
    <div className="answer">
      <p>{turn.reply}</p>
      {result?.rows && result.rows.length > 1 && (
        <ol className="ranked">
          {result.rows.map((row) => (
            <li key={row.rank}>
              <span className="num rank-no">{row.rank}</span>
              <span className="rank-name">{row.name}</span>
              <span className="num rank-value">{format(result.unit, row.value)}</span>
            </li>
          ))}
        </ol>
      )}
      {points && <InlineChart points={points} format={(v) => format(result?.unit, v)} />}
    </div>
  )
}

export function Conversation({ turns, onAsk, busy, header }: { turns: Turn[]; onAsk: (q: string) => void; busy: boolean; header: React.ReactNode }) {
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy || !draft.trim()) return
    onAsk(draft)
    setDraft('')
  }

  return (
    <section className="panel conversation" aria-label="Conversation">
      {header}
      <div className="turns">
        {turns.length === 0 ? (
          <div className="welcome">
            <p className="welcome-lede">Ask about any NYC taxi or rideshare trip from 2019 to 2025. Every number comes from a query you can inspect, and anything I can’t answer, I decline.</p>
            <ul className="suggestions" aria-label="Suggested questions">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => onAsk(s)} disabled={busy}>{s}</button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          turns.map((turn) => (
            <article key={turn.id} className={`turn is-${turn.status}`}>
              <p className="question">{turn.question}</p>
              <Answer turn={turn} />
            </article>
          ))
        )}
        <div ref={end} />
      </div>
      <form className="ask" onSubmit={submit}>
        <input
          ref={input}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about trips, fares, tips, places, times…"
          aria-label="Your question"
          autoFocus
        />
        <button type="submit" disabled={busy || !draft.trim()} aria-label="Ask">
          <Icon name="send" />
        </button>
      </form>
    </section>
  )
}
