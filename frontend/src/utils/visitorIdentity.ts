const VISITOR_ID_KEY = 'vibelo-visitor-id'
let memoryVisitorId = ''

function createVisitorId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return `v_${crypto.randomUUID()}`
  return `v_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

export function getVisitorId() {
  if (typeof window === 'undefined') return ''
  if (memoryVisitorId) return memoryVisitorId
  let existing = ''
  try {
    existing = localStorage.getItem(VISITOR_ID_KEY) || ''
  } catch {
    // Browser persistence is optional; keep a stable ID for this page session.
  }
  if (existing && existing.length <= 64) {
    memoryVisitorId = existing
    return existing
  }
  const next = createVisitorId().slice(0, 64)
  memoryVisitorId = next
  try {
    localStorage.setItem(VISITOR_ID_KEY, next)
  } catch {
    // In-memory fallback is enough to de-duplicate this page session.
  }
  return next
}
