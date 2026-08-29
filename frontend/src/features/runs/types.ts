import type { ApiFailure, PermissionMode } from '../../shared/api/types'

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

export type ChangeCheckStatus = 'no_changes' | 'needs_check' | 'passed' | 'failed' | 'outdated'

export interface ChangeCheckSummary {
  status: ChangeCheckStatus
  change_version: number
  checked_version: number | null
  check_kind: 'test' | 'compile' | 'run' | null
  tool_sequence: number | null
  exit_code: number | null
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
  model_calls?: number
  tool_calls?: number
  duration_ms?: number | null
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
