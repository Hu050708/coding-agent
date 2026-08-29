import type { RunEventEnvelope, RunStatus, RunSummary } from './types'

export type ActivityTone = 'neutral' | 'active' | 'success' | 'warning' | 'danger'
export type ActivityStage = 'control' | 'decision' | 'execution' | 'feedback' | 'approval'

export interface ActivityItem {
  seq: number
  event: RunEventEnvelope['event']
  timestamp: string
  title: string
  detail: string | null
  detailCode: boolean
  meta: string | null
  tone: ActivityTone
  stage: ActivityStage
  stageLabel: string
}

export interface RunOutcomePresentation {
  title: string
  statusLabel: string
  description: string
  reasonLabel: string
  tone: Exclude<ActivityTone, 'active'>
}

const stageLabels: Record<ActivityStage, string> = {
  control: '控制',
  decision: '决策',
  execution: '执行',
  feedback: '反馈',
  approval: '审批',
}

const toolLabels: Record<string, string> = {
  list_files: '列出文件',
  read_file: '读取文件',
  search_text: '搜索代码',
  make_directory: '创建目录',
  write_file: '写入文件',
  replace_text: '修改文件',
  delete_file: '删除文件',
  run_command: '运行命令',
}

const reasonLabels: Record<string, string> = {
  model_final: '模型返回最终回答',
  verified_completion: '模型返回最终结果',
  max_model_calls: '达到模型调用上限',
  max_tool_calls: '达到工具调用上限',
  token_budget_exceeded: '达到 Token 上限',
  wall_time_exceeded: '达到运行时间上限',
  api_fatal_error: '模型接口错误',
  content_filtered: '响应被内容策略拦截',
  truncated_response: '模型响应被截断',
  protocol_error: '模型响应不符合工具协议',
  user_cancelled: '用户停止运行',
  internal_invariant_violation: '运行时内部约束被破坏',
  service_restarted: '服务重启中断运行',
}

function text(value: unknown, limit = 240): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.replace(/[\r\n\t]+/g, ' ').trim()
  return normalized ? normalized.slice(0, limit) : null
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function toolName(value: unknown): string {
  const name = text(value, 80) ?? '未知工具'
  const label = toolLabels[name]
  return label ? `${label} · ${name}` : name
}

function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return '未提供终止原因'
  return reasonLabels[reason] ?? reason.replaceAll('_', ' ')
}

export function presentRunEvent(envelope: RunEventEnvelope): ActivityItem {
  const data = envelope.data
  let title = '运行状态更新'
  let detail: string | null = null
  let detailCode = false
  let meta: string | null = null
  let tone: ActivityTone = 'neutral'
  let stage: ActivityStage = 'control'

  switch (envelope.event) {
    case 'run.accepted':
      title = '任务已接收'
      detail = '已写入会话，等待本机执行器'
      break
    case 'run.started':
      title = '本机执行器已启动'
      detail = '开始模型决策与工具反馈循环'
      tone = 'active'
      break
    case 'memory.loaded': {
      const count = number(data.loaded_count) ?? 0
      title = count > 0 ? `装载 ${count} 条工作区记忆` : '未装载工作区记忆'
      detail = count > 0 ? '记忆仅作参考，仍需根据当前代码验证' : null
      break
    }
    case 'model.completed': {
      title = '模型完成一次决策'
      const finishReason = text(data.finish_reason, 80)
      detail = finishReason === 'tool_calls'
        ? '模型选择调用本地工具获取事实'
        : finishReason === 'stop'
          ? '模型选择停止调用工具并给出回答'
          : finishReason
      const latency = number(data.latency_ms)
      meta = latency === null ? null : `${Math.max(0, Math.round(latency))} ms`
      tone = 'active'
      stage = 'decision'
      break
    }
    case 'tool.started': {
      title = toolName(data.tool_name)
      const command = text(data.argv_summary)
      const target = text(data.target)
      detail = command
        ? `命令：${command}`
        : target
          ? `目标：${target}`
          : '正在当前工作区内执行'
      detailCode = command !== null || target !== null
      tone = 'active'
      stage = 'execution'
      break
    }
    case 'tool.completed': {
      const ok = data.ok !== false && data.success !== false
      title = `${toolName(data.tool_name)}${ok ? '已返回' : '失败'}`
      const repeated = data.progress_warning === true
      const resultSummary = text(data.result_summary)
      detail = repeated
        ? '检测到完全重复的工具结果，已提示模型调整策略'
        : ok
          ? resultSummary ?? '结果已作为事实反馈给模型'
          : text(data.error_code) ?? '工具返回失败结果，模型可据此调整策略'
      detailCode = ok && resultSummary !== null && !repeated
      const duration = number(data.duration_ms)
      meta = duration === null ? null : `${Math.max(0, Math.round(duration))} ms`
      tone = repeated ? 'warning' : ok ? 'success' : 'danger'
      stage = 'feedback'
      break
    }
    case 'approval.required':
      title = '等待你的确认'
      detail = '待审批操作不会在确认前执行'
      tone = 'warning'
      stage = 'approval'
      break
    case 'approval.resolved':
      title = data.decision === 'reject' ? '操作已拒绝' : '操作已批准'
      detail = data.decision === 'reject' ? 'Agent 将收到拒绝结果' : '本次批准仅对当前操作生效'
      tone = data.decision === 'reject' ? 'warning' : 'success'
      stage = 'approval'
      break
    case 'run.finished':
      title = '控制循环已结束'
      detail = reasonLabel(text(data.reason, 128))
      tone = data.status === 'completed' ? 'neutral' : 'danger'
      break
    case 'run.interrupted':
      title = '运行被服务重启中断'
      detail = '消息和事件已保存，可以重新发起任务'
      tone = 'warning'
      break
    case 'stream.reset':
      title = '正在重新同步事件'
      detail = '本地界面正在恢复可重放的运行轨迹'
      break
  }

  return {
    seq: envelope.seq,
    event: envelope.event,
    timestamp: envelope.timestamp,
    title,
    detail,
    detailCode,
    meta,
    tone,
    stage,
    stageLabel: stageLabels[stage],
  }
}

export function presentRunOutcome(run: Pick<RunSummary, 'status' | 'reason' | 'error'>): RunOutcomePresentation {
  const presentations: Record<RunStatus, Omit<RunOutcomePresentation, 'reasonLabel'>> = {
    starting: {
      title: '运行正在启动',
      statusLabel: '进行中',
      description: '本机执行器尚未进入模型循环。',
      tone: 'neutral',
    },
    running: {
      title: 'Agent 正在工作',
      statusLabel: '进行中',
      description: '模型正在根据工具返回的事实继续决策。',
      tone: 'neutral',
    },
    waiting_approval: {
      title: '等待人工审批',
      statusLabel: '已暂停',
      description: '待审批操作尚未执行。',
      tone: 'warning',
    },
    cancelling: {
      title: '正在停止运行',
      statusLabel: '停止中',
      description: '已发送取消请求，正在等待当前操作安全退出。',
      tone: 'warning',
    },
    completed: {
      title: '模型已结束本次运行',
      statusLabel: '待外部验证',
      description: '模型已停止调用工具并给出最终回答；这不等于代码已经通过测试或独立验收。',
      tone: 'neutral',
    },
    failed: {
      title: '运行失败',
      statusLabel: '未验证',
      description: run.error?.message || '控制循环因错误终止，没有形成可验证的成功结论。',
      tone: 'danger',
    },
    cancelled: {
      title: '运行已停止',
      statusLabel: '未验证',
      description: '运行由用户停止，未形成可验证的成功结论。',
      tone: 'warning',
    },
    budget_exhausted: {
      title: '运行达到安全上限',
      statusLabel: '未验证',
      description: '控制循环按预算边界停止，最终结果不能视为任务成功。',
      tone: 'warning',
    },
    interrupted: {
      title: '运行被中断',
      statusLabel: '未验证',
      description: '服务重启打断了控制循环，可以根据已保存的会话重新发起任务。',
      tone: 'warning',
    },
  }

  return { ...presentations[run.status], reasonLabel: reasonLabel(run.reason) }
}
