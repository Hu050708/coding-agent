import type {
  ApprovalRequest,
  RunConsoleState,
  RunEventEnvelope,
  RunMemoryStatus,
  RunStatus,
  RunSummary,
  TimelineEvent,
  TimelineTone,
} from './types'

const TERMINAL_STATUSES = new Set<RunStatus>([
  'completed',
  'failed',
  'cancelled',
  'budget_exhausted',
])

export function createRunConsoleState(): RunConsoleState {
  return {
    health: { phase: 'idle', data: null, message: null },
    validation: { phase: 'idle', checkedValue: null, data: null, message: null },
    run: null,
    timeline: [],
    pendingApproval: null,
    stream: 'idle',
    action: 'idle',
    message: null,
  }
}

export function isTerminalStatus(status: RunStatus | undefined): boolean {
  return status !== undefined && TERMINAL_STATUSES.has(status)
}

export function applyRunSnapshot(state: RunConsoleState, run: RunSummary): void {
  state.run = run
  state.pendingApproval = run.pending_approval
  if (isTerminalStatus(run.status)) state.stream = 'closed'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function safeText(value: unknown, maxLength = 320): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.replace(/[\r\n\t]+/g, ' ').trim()
  if (!normalized) return null
  return normalized.slice(0, maxLength)
}

function safeNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function safeBoolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

function safeCount(value: unknown): number | null {
  const parsed = safeNumber(value)
  return parsed === null ? null : Math.max(0, Math.trunc(parsed))
}

function safeMemoryStatus(value: unknown): RunMemoryStatus | null {
  return value === 'pending' ||
    value === 'loaded' ||
    value === 'empty' ||
    value === 'disabled' ||
    value === 'unavailable'
    ? value
    : null
}

function safeMemoryIds(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  return value
    .filter((item): item is string => typeof item === 'string' && item.length > 0)
    .slice(0, 100)
}

function addUsage(run: RunSummary, value: unknown): void {
  const usage = asRecord(value)
  if (!usage) return
  const keys = [
    'prompt_tokens',
    'completion_tokens',
    'total_tokens',
    'prompt_cache_hit_tokens',
    'prompt_cache_miss_tokens',
  ] as const
  for (const key of keys) {
    const increment = safeCount(usage[key])
    if (increment !== null) run.usage[key] += increment
  }
}

function replaceUsage(run: RunSummary, value: unknown): void {
  const usage = asRecord(value)
  if (!usage) return
  const keys = [
    'prompt_tokens',
    'completion_tokens',
    'total_tokens',
    'prompt_cache_hit_tokens',
    'prompt_cache_miss_tokens',
  ] as const
  for (const key of keys) {
    const next = safeCount(usage[key])
    if (next !== null) run.usage[key] = next
  }
}

function approvalFromData(data: Record<string, unknown>): ApprovalRequest | null {
  const approval = asRecord(data.approval)
  if (!approval || typeof approval.approval_id !== 'string') return null
  return {
    approval_id: approval.approval_id,
    argv: Array.isArray(approval.argv)
      ? approval.argv.filter((item): item is string => typeof item === 'string').slice(0, 64)
      : [],
    cwd: safeText(approval.cwd, 1024) ?? '.',
    reason: safeText(approval.reason, 500) ?? '该命令需要人工确认。',
    created_at: safeText(approval.created_at, 64) ?? '',
    expires_at: safeText(approval.expires_at, 64) ?? '',
  }
}

function eventPresentation(envelope: RunEventEnvelope): {
  title: string
  detail: string | null
  tone: TimelineTone
} {
  const data = envelope.data
  switch (envelope.event) {
    case 'run.accepted':
      return { title: '任务已接收', detail: '等待本机执行器启动', tone: 'neutral' }
    case 'run.started':
      return { title: '运行已开始', detail: null, tone: 'active' }
    case 'memory.loaded':
      return { title: '项目记忆已准备', detail: null, tone: 'neutral' }
    case 'model.completed':
      return {
        title: '模型完成一次决策',
        detail: safeText(data.finish_reason) ?? safeText(data.summary),
        tone: 'active',
      }
    case 'tool.started':
      return {
        title: `${safeText(data.tool_name, 80) ?? '工具'} 开始`,
        detail: safeText(data.path, 240),
        tone: 'active',
      }
    case 'tool.completed': {
      const success = safeBoolean(data.ok) ?? safeBoolean(data.success)
      return {
        title: `${safeText(data.tool_name, 80) ?? '工具'} ${success === false ? '失败' : '完成'}`,
        detail: safeText(data.error_code, 100),
        tone: success === false ? 'danger' : 'success',
      }
    }
    case 'approval.required':
      return { title: '等待命令审批', detail: '运行已暂停', tone: 'warning' }
    case 'approval.resolved':
      return {
        title: data.decision === 'reject' ? '命令已拒绝' : '命令已批准',
        detail: null,
        tone: data.decision === 'reject' ? 'warning' : 'success',
      }
    case 'run.finished':
      return {
        title: data.status === 'completed' ? '运行完成' : '运行已结束',
        detail: safeText(data.reason, 300),
        tone: data.status === 'completed' ? 'success' : data.status === 'cancelled' ? 'warning' : 'danger',
      }
    case 'stream.reset':
      return { title: '事件流已重新同步', detail: '正在刷新运行状态', tone: 'neutral' }
  }
}

export function toTimelineEvent(envelope: RunEventEnvelope): TimelineEvent {
  const presentation = eventPresentation(envelope)
  return {
    seq: envelope.seq,
    event: envelope.event,
    timestamp: envelope.timestamp,
    title: presentation.title,
    detail: presentation.detail,
    tone: presentation.tone,
    toolName: safeText(envelope.data.tool_name, 80),
    durationMs: safeNumber(envelope.data.duration_ms),
    exitCode: safeNumber(envelope.data.exit_code),
    truncated: safeBoolean(envelope.data.truncated),
  }
}

export function applyRunEvent(state: RunConsoleState, envelope: RunEventEnvelope): void {
  if (state.timeline.some((item) => item.seq === envelope.seq)) return
  state.timeline.push(toTimelineEvent(envelope))
  state.timeline.sort((left, right) => left.seq - right.seq)

  if (state.run && envelope.event === 'model.completed') {
    const sequence = safeCount(envelope.data.sequence)
    state.run.model_calls = Math.max(state.run.model_calls, sequence ?? state.run.model_calls + 1)
    addUsage(state.run, envelope.data.usage)
  }
  if (state.run && (envelope.event === 'tool.started' || envelope.event === 'tool.completed')) {
    const sequence = safeCount(envelope.data.sequence)
    state.run.tool_calls = Math.max(state.run.tool_calls, sequence ?? state.run.tool_calls + 1)
  }

  if (envelope.event === 'approval.required') {
    state.pendingApproval = approvalFromData(envelope.data)
    if (state.run) state.run.status = 'waiting_approval'
  }
  if (envelope.event === 'approval.resolved') {
    state.pendingApproval = null
    if (state.run && !isTerminalStatus(state.run.status)) state.run.status = 'running'
  }
  if (envelope.event === 'run.started' && state.run) state.run.status = 'running'
  if (envelope.event === 'memory.loaded' && state.run) {
    const status = safeMemoryStatus(envelope.data.status)
    const loadedCount = safeCount(envelope.data.loaded_count)
    const loadedIds = safeMemoryIds(envelope.data.loaded_ids)
    if (status !== null) state.run.memory.status = status
    if (loadedCount !== null) state.run.memory.loaded_count = loadedCount
    if (loadedIds !== null) state.run.memory.loaded_ids = loadedIds
  }
  if (envelope.event === 'run.finished' && state.run) {
    const status = envelope.data.status
    if (typeof status === 'string' && isTerminalStatus(status as RunStatus)) {
      state.run.status = status as RunStatus
    }
    const modelCalls = safeCount(envelope.data.model_calls)
    const toolCalls = safeCount(envelope.data.tool_calls)
    const duration = safeNumber(envelope.data.duration_seconds)
    if (modelCalls !== null) state.run.model_calls = modelCalls
    if (toolCalls !== null) state.run.tool_calls = toolCalls
    if (duration !== null) state.run.duration_seconds = Math.max(0, duration)
    if (typeof envelope.data.reason === 'string') state.run.reason = envelope.data.reason
    replaceUsage(state.run, envelope.data.usage)
  }
}

export function resetRunState(state: RunConsoleState): void {
  state.run = null
  state.timeline = []
  state.pendingApproval = null
  state.stream = 'idle'
  state.message = null
}
