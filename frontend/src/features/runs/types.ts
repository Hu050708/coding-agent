export type RunStatus =
  | 'starting'
  | 'running'
  | 'waiting_approval'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'budget_exhausted'

export interface UsageSummary {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  prompt_cache_hit_tokens: number
  prompt_cache_miss_tokens: number
}

export interface ApiFailure {
  code: string
  message: string
}

export interface ApprovalRequest {
  approval_id: string
  argv: string[]
  cwd: string
  reason: string
  created_at: string
  expires_at: string
}

export type RunMemoryStatus = 'pending' | 'loaded' | 'empty' | 'disabled' | 'unavailable'

export interface RunMemorySummary {
  status: RunMemoryStatus
  loaded_count: number
  loaded_ids: string[]
}

export interface RunSummary {
  run_id: string
  status: RunStatus
  workspace: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  final_content: string | null
  reason: string | null
  error: ApiFailure | null
  model_calls: number
  tool_calls: number
  usage: UsageSummary
  duration_seconds: number | null
  pending_approval: ApprovalRequest | null
  cancel_requested: boolean
  memory: RunMemorySummary
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  service: string
  api_key_configured: boolean
  model: string
  allowed_root: string
  max_active_runs: number
  active_runs: number
  max_model_calls: number
  max_tool_calls: number
  max_total_tokens: number
  wall_time_seconds: number
}

export interface WorkspaceValidationResponse {
  valid: true
  workspace: string
  allowed_root: string
}

export interface ApprovalDecisionResponse {
  run_id: string
  approval_id: string
  decision: 'approve' | 'reject'
  accepted: true
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
  'stream.reset',
] as const

export type RunEventName = (typeof RUN_EVENT_NAMES)[number]

export interface RunEventEnvelope {
  seq: number
  event: RunEventName
  timestamp: string
  data: Record<string, unknown>
}

export interface CreateRunRequest {
  workspace: string
  task: string
  use_memory: boolean
}

export interface ApiClient {
  health(signal?: AbortSignal): Promise<HealthResponse>
  validateWorkspace(workspace: string, signal?: AbortSignal): Promise<WorkspaceValidationResponse>
  createRun(request: CreateRunRequest, signal?: AbortSignal): Promise<RunSummary>
  getRun(runId: string, signal?: AbortSignal): Promise<RunSummary>
  cancelRun(runId: string, signal?: AbortSignal): Promise<RunSummary>
  decideApproval(
    runId: string,
    approvalId: string,
    decision: 'approve' | 'reject',
    signal?: AbortSignal,
  ): Promise<ApprovalDecisionResponse>
}

export type AsyncPhase = 'idle' | 'loading' | 'success' | 'error'
export type StreamPhase = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed'
export type TimelineTone = 'neutral' | 'active' | 'success' | 'warning' | 'danger'

export interface TimelineEvent {
  seq: number
  event: RunEventName
  timestamp: string
  title: string
  detail: string | null
  tone: TimelineTone
  toolName: string | null
  durationMs: number | null
  exitCode: number | null
  truncated: boolean | null
}

export interface HealthState {
  phase: AsyncPhase
  data: HealthResponse | null
  message: string | null
}

export interface WorkspaceValidationState {
  phase: AsyncPhase
  checkedValue: string | null
  data: WorkspaceValidationResponse | null
  message: string | null
}

export interface RunConsoleState {
  health: HealthState
  validation: WorkspaceValidationState
  run: RunSummary | null
  timeline: TimelineEvent[]
  pendingApproval: ApprovalRequest | null
  stream: StreamPhase
  action: 'idle' | 'starting' | 'cancelling' | 'approving' | 'rejecting'
  message: string | null
}
