// One small authored icon set: 16px grid, 1.6 stroke, round caps.
const PATHS = {
  send: 'M3 8h9M8.5 4.5 12 8l-3.5 3.5',
  check: 'M3.5 8.5 6.5 11.5 12.5 4.5',
  cross: 'M4.5 4.5 11.5 11.5M11.5 4.5 4.5 11.5',
  slash: 'M5 12.5 11 3.5',
}

export function Icon({ name }: { name: keyof typeof PATHS }) {
  return (
    <svg className="icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d={PATHS[name]} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
