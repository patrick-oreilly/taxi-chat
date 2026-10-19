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
  // Trend results (#6) are expected to carry a series; the chart reads either key.
  series?: { label?: string; period?: string; value: number }[]
  [key: string]: unknown
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
