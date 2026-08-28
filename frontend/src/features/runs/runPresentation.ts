import type { RunEventEnvelope } from '../../shared/api/types'

export type ActivityTone = 'neutral' | 'active' | 'success' | 'warning' | 'danger'

export interface ActivityItem {
  seq: number
  event: RunEventEnvelope['event']
  timestamp: string
  title: string
  detail: string | null
  meta: string | null
  tone: ActivityTone
}

function text(value: unknown, limit = 240): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.replace(/[\r\n\t]+/g, ' ').trim()
  return normalized ? normalized.slice(0, limit) : null
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function presentRunEvent(envelope: RunEventEnvelope): ActivityItem {
  const data = envelope.data
  let title = '运行状态更新'
  let detail: string | null = null
  let meta: string | null = null
  let tone: ActivityTone = 'neutral'

  switch (envelope.event) {
    case 'run.accepted':
      title = '任务已接收'
      detail = '已写入会话，等待本机执行器'
      break
    case 'run.started':
      title = '开始处理'
      tone = 'active'
      break
    case 'memory.loaded': {
      const count = number(data.loaded_count) ?? 0
      title = count > 0 ? `已读取 ${count} 条工作区记忆` : '没有使用工作区记忆'
      break
    }
    case 'model.completed':
      title = '模型完成一次决策'
      detail = text(data.summary) ?? text(data.finish_reason)
      tone = 'active'
      break
    case 'tool.started':
      title = `${text(data.tool_name, 80) ?? '工具'} 正在执行`
      detail = text(data.path_label) ?? text(data.summary)
      tone = 'active'
      break
    case 'tool.completed': {
      const ok = data.ok !== false && data.success !== false
      title = `${text(data.tool_name, 80) ?? '工具'}${ok ? '完成' : '失败'}`
      const repeated = data.progress_warning === true
      detail = repeated
        ? '检测到完全重复的工具结果，已提示模型调整策略'
        : text(data.summary) ?? text(data.error_code)
      const duration = number(data.duration_ms)
      meta = duration === null ? null : `${Math.max(0, Math.round(duration))} ms`
      tone = repeated ? 'warning' : ok ? 'success' : 'danger'
      break
    }
    case 'approval.required':
      title = '等待你的确认'
      detail = '命令不会在确认前执行'
      tone = 'warning'
      break
    case 'approval.resolved':
      title = data.decision === 'reject' ? '命令已拒绝' : '命令已批准'
      tone = data.decision === 'reject' ? 'warning' : 'success'
      break
    case 'run.finished':
      title = data.status === 'completed' ? '任务完成' : '任务结束'
      detail = text(data.reason)
      tone = data.status === 'completed' ? 'success' : 'danger'
      break
    case 'run.interrupted':
      title = '运行被服务重启中断'
      detail = '消息和事件已保存，可以重新发起任务'
      tone = 'warning'
      break
    case 'stream.reset':
      title = '正在重新同步事件'
      tone = 'neutral'
      break
  }

  return {
    seq: envelope.seq,
    event: envelope.event,
    timestamp: envelope.timestamp,
    title,
    detail,
    meta,
    tone,
  }
}
