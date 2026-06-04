// Sync configuration file for ElectricSQL
// Controls what data is synced between PostgreSQL and the browser PGlite.

// ElectricSQL uses "shapes" to define what data each client subscribes to.
// Shape definitions use a subset of SQL WHERE clauses.

export const SHAPES = {
  // Sync all conversations (filtering can be added later)
  conversations: {
    table: 'conversations',
    where: undefined, // sync all rows
  },

  // Sync all sessions
  sessions: {
    table: 'sessions',
    where: undefined,
  },
}

// The ElectricSQL sync service URL
export const ELECTRIC_URL =
  import.meta.env.VITE_ELECTRIC_URL || 'ws://localhost:5133'
