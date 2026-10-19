// Shapes of what the server streams. They mirror taxichat/trace.py and the
// events in taxichat/pipeline.py; only the fields the interface reads are typed.

export type Detail = { value: string | null; confidence: number | null; defaulted?: boolean }

export type Check = { name: string; passed: boolean; detail: string }

export type RankedRow = { rank: number; id: number | string; name: string; borough: string; value: number; trips: number }

export type Result = {
  measure?: string
  unit?: string
  value?: number | null
  trips?: number
  rows?: RankedRow[]
  rank_unit?: string
  direction?: string
  grain?: 'day' | 'week' | 'month' | 'year'
  series?: { t: string; value: number | null; trips: number; complete: boolean }[]
  groups?: { label: string; value: number | null; trips: number }[]
  variable?: string
  buckets?: { from: number | null; to: number | null; trips: number; share: number | null }[]
  threshold?: number
  share_below?: number | null
  [key: string]: unknown
}

export type Derived = Record<string, unknown> & {
  pct_change?: number | null
  ratio?: number | null
  pct_difference?: number | null
  difference?: number | null
  peak?: { t: string; value: number }
}

export type Trace = {
  question: string
  intent: Detail | null
  details: Record<string, Detail>
  assumptions: string[]
  declined: string | null
  decline_message: string | null
  decline_source?: string | null
  query: string | null
  source: string | null
  rows_scanned: number | null
  result: Result | null
  derived?: Derived | null
  notes?: string[]
  reply: string | null
  reply_source: string | null
  checks: Check[]
  timings_ms: Record<string, number>
  period: { label: string } | null
}

export type LitZone = { id: number; rank: number | null; value: number | null; label: string; group?: 'a' | 'b' }

export type Highlight = { mode: 'ranking' | 'place' | 'compare' | 'city' | 'declined'; zones: LitZone[] }

export type StageEvent = { stage: string } & Record<string, unknown>

export type TurnStatus = 'streaming' | 'answered' | 'declined' | 'error'

export type Turn = {
  id: number
  question: string
  status: TurnStatus
  reply?: string
  declineMessage?: string
  events: StageEvent[]
  trace?: Trace
  highlight?: Highlight
  startedAt: number
  finishedAt?: number
}
