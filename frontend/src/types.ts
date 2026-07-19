// --- Shared domain types ---

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export interface Session {
  id: string
  routing_key: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ApiResponse {
  msg_id: string
  reply: string
  session_id: string
  duration_ms: number
}

export interface CurrentUser {
  id: number
  username: string
  created_at?: string
}
