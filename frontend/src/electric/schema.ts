// ElectricSQL schema definition for 玄机
// Matches PostgreSQL tables: conversations, sessions

export interface DbConversation {
  id: string
  session_id: string
  routing_key: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface DbSession {
  id: string
  routing_key: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface DbSchema {
  conversations: DbConversation
  sessions: DbSession
}

// ElectricSQL table definitions
export const schema = {
  conversations: {
    id: { type: 'TEXT', primaryKey: true },
    session_id: { type: 'TEXT', notNull: true },
    routing_key: { type: 'TEXT', notNull: true },
    role: { type: 'TEXT', notNull: true },
    content: { type: 'TEXT', notNull: true },
    created_at: { type: 'TIMESTAMPTZ', notNull: true, default: 'NOW()' },
  },
  sessions: {
    id: { type: 'TEXT', primaryKey: true },
    routing_key: { type: 'TEXT', notNull: true },
    title: { type: 'TEXT', notNull: true, default: "''" },
    message_count: { type: 'INT', notNull: true, default: 0 },
    created_at: { type: 'TIMESTAMPTZ', notNull: true, default: 'NOW()' },
    updated_at: { type: 'TIMESTAMPTZ', notNull: true, default: 'NOW()' },
  },
}
