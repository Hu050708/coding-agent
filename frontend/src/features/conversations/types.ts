import type { PermissionMode } from '../../shared/api/types'

export interface Conversation {
  id: string
  workspace_id: string
  title: string
  default_permission_mode: PermissionMode
  use_memory: boolean
  active_run_id: string | null
  created_at: string
  updated_at: string
}

export type MessageRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  conversation_id: string
  run_id: string | null
  role: MessageRole
  content: string
  seq: number
  created_at: string
}
