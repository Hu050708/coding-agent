export type PermissionMode = 'ask' | 'agent' | 'workspace_full'

export interface ApiFailure {
  code: string
  message: string
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  service: string
  model: string
  database: 'ready' | 'unavailable'
  provider_configured: boolean
  allowed_root_label?: string
}

export interface Workspace {
  id: string
  display_name: string
  path_hint?: string
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface DirectoryEntry {
  name: string
  path: string
  selectable: boolean
}

export interface DirectoryListing {
  current_path: string
  parent_path: string | null
  allowed_root: string
  entries: DirectoryEntry[]
}

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

export type RunStatus =
  | 'starting'
  | 'running'
  | 'waiting_approval'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'budget_exhausted'
  | 'interrupted'

export interface UsageSummary {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface ApprovalRequest {
  id: string
  run_id: string
  tool_name: string
  action_summary: string
  argv: string[]
  cwd_label: string
  reason: string
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  created_at: string
  expires_at: string | null
}

export interface RunSummary {
  id: string
  conversation_id: string
  workspace_id: string
  status: RunStatus
  permission_mode: PermissionMode
  use_memory: boolean
  model: string
  final_content: string | null
  reason: string | null
  error: ApiFailure | null
  pending_approval: ApprovalRequest | null
  usage: UsageSummary
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export const RUN_EVENT_NAMES = [
  'run.accepted',
  'run.started',
  'memory.loaded',
  'model.completed',
  'tool.started',
  'tool.completed',
  'approval.required',
  'approval.resolved',
  'run.finished',
  'run.interrupted',
  'stream.reset',
] as const

export type RunEventName = (typeof RUN_EVENT_NAMES)[number]

export interface RunEventEnvelope {
  seq: number
  event: RunEventName
  timestamp: string
  data: Record<string, unknown>
}

export interface MemoryEntry {
  id: string
  workspace_id: string
  kind: 'preference' | 'fact' | 'decision' | 'note'
  content: string
  pinned: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}
