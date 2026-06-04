// ElectricSQL client for browser-side PGlite database.
// Provides local SQLite database for offline-capable conversations.
// Real-time PostgreSQL sync is OPTIONAL - the app works via REST API.

const ELECTRIC_URL = import.meta.env.VITE_ELECTRIC_URL || 'ws://localhost:5133'

let _db: any = null
let _ready = false

export function isReady(): boolean {
  return _ready
}

export async function initElectric(): Promise<any> {
  if (_db) return _db
  try {
    const { PGlite } = await import('@electric-sql/pglite')
    _db = new PGlite('idb://xiaopaw')
    await _db.waitForReady?.()
    _ready = true
    console.log('ElectricSQL: PGlite database ready')
    return _db
  } catch (err) {
    console.warn('ElectricSQL: PGlite not available (optional):', err)
    _ready = true
    return null
  }
}

export async function connectSync() {
  // Stub for future ElectricSQL sync integration.
  // When the ElectricSQL sync service is running, this will connect
  // the local PGlite to PostgreSQL via WebSocket.
  console.log(`ElectricSQL: sync would connect to ${ELECTRIC_URL}`)
}
