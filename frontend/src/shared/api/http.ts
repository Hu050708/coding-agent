import type { ApiFailure } from './types'

export class ApiRequestError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, failure: ApiFailure) {
    super(failure.message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = failure.code
  }
}

type FetchLike = typeof fetch

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function readPayload(response: Response): Promise<unknown> {
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) return null
  try {
    return await response.json()
  } catch {
    return null
  }
}

function failureFrom(payload: unknown, status: number): ApiFailure {
  let detail: unknown = payload
  if (isRecord(payload) && 'error' in payload) detail = payload.error
  if (isRecord(payload) && 'detail' in payload) detail = payload.detail
  if (isRecord(detail)) {
    return {
      code: typeof detail.code === 'string' ? detail.code : 'request_failed',
      message:
        typeof detail.message === 'string'
          ? detail.message
          : `请求失败（HTTP ${status}）`,
    }
  }
  return {
    code: status === 422 ? 'validation_error' : 'request_failed',
    message: typeof detail === 'string' ? detail : `请求失败（HTTP ${status}）`,
  }
}

export function localizedError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const messages: Record<string, string> = {
      database_unavailable: 'PostgreSQL 暂时不可用。请启动 coding-agent-postgres 后重试。',
      provider_not_configured: 'DeepSeek 接口尚未配置，当前无法开始任务。',
      workspace_busy: '这个工作区已有任务在运行。结束它后再开始新任务。',
      workspace_not_found: '工作区不存在或已经归档。',
      workspace_not_allowed: '只能选择后端允许根目录中的文件夹。',
      conversation_not_found: '会话不存在或已被删除。',
      run_not_found: '运行不存在，可能已被服务重启清理。',
      approval_stale: '这项审批已经失效，请刷新运行状态。',
      approval_not_pending: '这项审批已经处理。',
      evaluation_run_not_found: '这份评测记录不存在或已经被移走。',
      evaluation_report_invalid: '评测报告无法读取，请重新生成 benchmark 报告。',
      run_cancelling: '任务正在停止，不能继续审批。',
      validation_error: '提交内容不完整，请检查后重试。',
    }
    return messages[error.code] ?? error.message
  }
  if (error instanceof Error && error.name === 'AbortError') return ''
  if (error instanceof TypeError) return '无法连接本机后端，请确认 FastAPI 服务已经启动。'
  if (error instanceof Error && error.message) return error.message
  return '本机服务暂时无法完成请求。'
}

export interface HttpClient {
  request<T>(path: string, init?: RequestInit): Promise<T>
}

export function createHttpClient(fetchImpl: FetchLike = globalThis.fetch): HttpClient {
  return {
    async request<T>(path: string, init: RequestInit = {}): Promise<T> {
      let response: Response
      try {
        response = await fetchImpl(path, {
          ...init,
          headers: {
            Accept: 'application/json',
            ...(init.body ? { 'Content-Type': 'application/json' } : {}),
            ...init.headers,
          },
        })
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') throw error
        throw new TypeError('network_error')
      }
      const payload = await readPayload(response)
      if (!response.ok) throw new ApiRequestError(response.status, failureFrom(payload, response.status))
      return payload as T
    },
  }
}

export const httpClient = createHttpClient()
