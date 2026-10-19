import type { ReactNode } from 'react'

import { Icon } from './Icon'
import type { Detail, StageEvent, Turn } from './types'

const DETAIL_LABELS: [key: string, label: string][] = [
  ['measure', 'Measure'],
  ['service', 'Service'],
  ['place', 'Place'],
  ['place_role', 'Trips'],
  ['year', 'Year'],
  ['month', 'Month'],
  ['day', 'Day'],
  ['time_of_day', 'Time'],
  ['direction', 'Ranking'],
  ['rank_unit', 'Ranked by'],
]
const UNSTATED = new Set(['not_stated', 'no_place'])
const RANKING_ONLY = new Set(['direction', 'rank_unit'])
const LOW_CONFIDENCE = 0.6

const SOURCES: Record<string, string> = {
  llm: 'Phrased by DeepSeek, numbers checked',
  llm_retry: 'Phrased by DeepSeek on its second attempt',
  template: 'Fixed template (the language model’s reply failed a check)',
}

const DECLINE_SOURCES: Record<string, string> = {
  fixed: 'Decided in code, fixed message',
  llm: 'Decided in code, phrased by DeepSeek and checked',
  llm_retry: 'Decided in code, phrased by DeepSeek on its second attempt',
  template: 'Decided in code, fixed message (the phrasing failed a check)',
}

const NAMES: Record<string, string> = {
  all: 'All services',
  yellow: 'Yellow taxis',
  green: 'Green taxis',
  rideshare: 'Rideshare',
  uber: 'Uber',
  lyft: 'Lyft',
  total_or_average: 'Total or average',
  out_of_scope: 'Out of scope',
  trip_count: 'Trips',
  rush_hour: 'Rush hour',
  most_recent: 'Most recent',
}

function words(value: string | null | undefined) {
  if (!value) return '—'
  if (NAMES[value]) return NAMES[value]
  const [kind, rest] = value.split(':')
  if (rest && kind === 'zone') return `Zone ${rest}`
  const text = (rest ?? value).replace(/_/g, ' ')
  return rest ? text.replace(/\b\w/g, (c) => c.toUpperCase()) : text.charAt(0).toUpperCase() + text.slice(1)
}

function Confidence({ value }: { value: number | null | undefined }) {
  if (value == null) return null
  const low = value < LOW_CONFIDENCE
  return (
    <span className={`conf${low ? ' is-low' : ''}`} title="Jev's confidence">
      <span className="conf-bar" style={{ ['--v' as string]: value }} />
      <span className="mono">{value.toFixed(2)}</span>
    </span>
  )
}

function Step({ title, at, state, children }: { title: string; at?: number; state: 'done' | 'active' | 'waiting' | 'failed'; children?: ReactNode }) {
  return (
    <li className={`step is-${state}`}>
      <div className="step-head">
        <span className="step-dot" aria-hidden />
        <h3>{title}</h3>
        {at != null && <span className="mono step-at">{Math.round(at)} ms</span>}
      </div>
      {children && <div className="step-body">{children}</div>}
    </li>
  )
}

function find(events: StageEvent[], stage: string) {
  return events.find((e) => e.stage === stage)
}

export function TracePanel({ turn }: { turn?: Turn }) {
  if (!turn) {
    return (
      <aside className="panel trace" aria-label="How I got this">
        <header className="panel-head"><h2>How I got this</h2></header>
        <p className="trace-empty">
          Ask a question and every step shows up here as it happens: how Jev read it, what code resolved, the query that ran
          and the checks the reply had to pass.
        </p>
      </aside>
    )
  }

  const { events, status } = turn
  const classified = find(events, 'classified')
  const resolved = find(events, 'resolved')
  const queried = find(events, 'queried')
  const checks = events.filter((e) => e.stage === 'checked')
  const written = find(events, 'written')
  const declined = find(events, 'declined')
  const error = find(events, 'error')
  const streaming = status === 'streaming'
  const next = (seen: boolean) => (seen ? 'done' : streaming ? 'active' : 'waiting')

  const intent = classified?.intent as Detail | undefined
  const details = (classified?.details ?? {}) as Record<string, Detail>
  const result = queried?.result as Record<string, unknown> | undefined

  return (
    <aside className="panel trace" aria-label="How I got this" aria-live="polite">
      <header className="panel-head">
        <h2>How I got this</h2>
        {turn.finishedAt && <span className="mono muted">{Math.round(turn.finishedAt - turn.startedAt)} ms total</span>}
      </header>
      <ol className="steps">
        <Step title="Read by Jev" at={classified?.at as number} state={next(!!classified)}>
          {intent && (
            <>
              <div className="intent">
                <span className="intent-name">{words(intent.value)}</span>
                <Confidence value={intent.confidence} />
              </div>
              <dl className="details">
                {DETAIL_LABELS.filter(([key]) => details[key] && !UNSTATED.has(details[key].value ?? '') && (intent.value === 'ranking' || !RANKING_ONLY.has(key))).map(([key, label]) => (
                  <div key={key} className="detail-row">
                    <dt>{label}</dt>
                    <dd>{key === 'place' && resolved?.place ? String(resolved.place) : words(details[key].value)}</dd>
                    <Confidence value={details[key].confidence} />
                  </div>
                ))}
              </dl>
              <p className="guards mono">
                injection {(classified!.injection as number).toFixed(2)}
                {typeof classified!.compound === 'number' && <> · compound {(classified!.compound as number).toFixed(2)}</>}
              </p>
            </>
          )}
        </Step>

        {(resolved || !declined) && (
          <Step title="Resolved in code" at={resolved?.at as number} state={declined && !resolved ? 'waiting' : next(!!resolved)}>
            {resolved && (
              <>
                <p className="resolved">
                  {[resolved.period, words(resolved.service as string), resolved.place, resolved.day && words(resolved.day as string).toLowerCase(), resolved.time_of_day && words(resolved.time_of_day as string).toLowerCase()]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                {(resolved.assumptions as string[]).length > 0 && (
                  <ul className="assumptions">
                    {(resolved.assumptions as string[]).map((a) => <li key={a}>Assumed {a}</li>)}
                  </ul>
                )}
              </>
            )}
          </Step>
        )}

        {!declined && (
          <Step title="Queried" at={queried?.at as number} state={next(!!queried)}>
            {queried && (
              <>
                <div className="query-line">
                  <span className={`source-tag is-${queried.source}`}>{queried.source === 'raw' ? 'Raw trips' : 'Hourly rollups'}</span>
                  <span className="num">{(queried.rows_scanned as number).toLocaleString('en-US')} rows</span>
                </div>
                <details className="sql">
                  <summary>Show the SQL</summary>
                  <pre className="mono">{String(queried.sql).replace(/ (FROM|WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|SELECT|JOIN)\b/g, '\n$1')}</pre>
                  <p className="mono params">params: {(queried.params as string[]).join(', ')}</p>
                </details>
                {result && 'value' in result && result.value == null && <p className="muted">No matching trips.</p>}
              </>
            )}
          </Step>
        )}

        {(checks.length > 0 || (!declined && streaming && queried)) && (
          <Step title="Checked" state={checks.length ? (checks.some((c) => c.passed) || written ? 'done' : 'failed') : 'active'}>
            <ul className="checks">
              {checks.map((c, i) => (
                <li key={i} className={c.passed ? 'is-pass' : 'is-fail'}>
                  <Icon name={c.passed ? 'check' : 'cross'} />
                  <span>
                    {c.attempt === 'llm_retry' ? 'Second attempt' : 'First attempt'}: {c.passed ? 'every number traced to the result' : (c.detail as string)}
                  </span>
                </li>
              ))}
            </ul>
          </Step>
        )}

        {written && (
          <Step title="Answered" at={written.at as number} state="done">
            <p className="muted">{SOURCES[written.source as string] ?? String(written.source)}</p>
          </Step>
        )}

        {declined && (
          <Step title="Declined" at={declined.at as number} state="failed">
            <p className="decline-code">{words(String(declined.reason))}</p>
            {turn.trace?.decline_source && <p className="muted">{DECLINE_SOURCES[turn.trace.decline_source] ?? turn.trace.decline_source}</p>}
          </Step>
        )}

        {error && (
          <Step title="Something broke" state="failed">
            <p className="muted">{String(error.message)}</p>
          </Step>
        )}
      </ol>
    </aside>
  )
}
