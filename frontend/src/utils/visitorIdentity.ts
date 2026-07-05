const VISITOR_ID_KEY = 'vibelo-visitor-id'

function createVisitorId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return `v_${crypto.randomUUID()}`
  return `v_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

export function getVisitorId() {
  if (typeof window === 'undefined') return ''
  const existing = localStorage.getItem(VISITOR_ID_KEY)
  if (existing && existing.length <= 64) return existing
  const next = createVisitorId().slice(0, 64)
  localStorage.setItem(VISITOR_ID_KEY, next)
  return next
}
