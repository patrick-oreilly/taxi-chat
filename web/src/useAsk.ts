import { useCallback, useEffect, useRef, useState } from 'react'

import type { Highlight, StageEvent, Trace, Turn } from './types'

// Each question opens one EventSource on /api/ask; every streamed stage is kept
// on its turn so the trace panel can replay exactly what happened.
export function useAsk() {
  const [turns, setTurns] = useState<Turn[]>([])
  const source = useRef<EventSource | null>(null)
  const nextId = useRef(1)

  useEffect(() => () => source.current?.close(), [])

  const update = (id: number, change: (turn: Turn) => Turn) =>
    setTurns((all) => all.map((turn) => (turn.id === id ? change(turn) : turn)))

  const ask = useCallback((question: string) => {
    const text = question.trim()
    if (!text) return
    source.current?.close()
    const id = nextId.current++
    setTurns((all) => [...all, { id, question: text, status: 'streaming', events: [], startedAt: performance.now() }])

    const stream = new EventSource(`/api/ask?q=${encodeURIComponent(text)}`)
    source.current = stream
    stream.onmessage = (message) => {
      const event = JSON.parse(message.data) as StageEvent
      const arrived = performance.now()
      update(id, (turn) => {
        const stamped = { ...event, at: arrived - turn.startedAt }
        const next: Turn = { ...turn, events: event.stage === 'done' ? turn.events : [...turn.events, stamped] }
        if (event.stage === 'written') next.reply = event.reply as string
        if (event.stage === 'declined') next.declineMessage = event.message as string
        if (event.stage === 'error') {
          next.status = 'error'
          next.declineMessage = event.message as string
          next.finishedAt = performance.now()
        }
        if (event.stage === 'done') {
          const trace = event.trace as Trace
          next.trace = trace
          next.highlight = event.highlight as Highlight
          next.status = trace.declined ? 'declined' : 'answered'
          next.declineMessage = trace.decline_message ?? undefined
          next.reply = trace.reply ?? next.reply
          next.finishedAt = performance.now()
        }
        return next
      })
      if (event.stage === 'done' || event.stage === 'error') stream.close()
    }
    stream.onerror = () => {
      stream.close()
      update(id, (turn) =>
        turn.status === 'streaming'
          ? { ...turn, status: 'error', declineMessage: 'Lost the connection to the server. Is it running?', finishedAt: performance.now() }
          : turn,
      )
    }
  }, [])

  return { turns, ask }
}
