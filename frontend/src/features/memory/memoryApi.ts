import type {
  CreateMemoryRequest,
  MemoryApi,
  MemoryEntry,
  UpdateMemoryRequest,
} from './types'

export type { MemoryApi } from './types'

type FetchLike = typeof fetch

interface ApiFailure {
  code: string
  message: string
}

export class MemoryApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, failure: ApiFailure) {
    super(failure.message)
    this.name = 'MemoryApiError'
    this.status = status
    this.code = failure.code
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

function hasChineseText(value: string): boolean {
  return /[\u3400-\u9fff]/u.test(value)
}

function localizedMessage(code: string, rawMessage: string | null, status: number): string {
  const messages: Record<string, string> = {
    network_error: '无法连接本机记忆服务，请确认后端已经启动。',
    memory_not_found: '这条记忆不存在或已被删除。',
    memory_workspace_mismatch: '这条记忆不属于当前工作区。',
    memory_workspace_denied: '当前工作区没有访问这条记忆的权限。',
    memory_store_unavailable: '记忆存储暂时不可用，本次操作没有完成。',
    memory_workspace_busy: '运行期间项目记忆只读，请在任务结束后再修改。',
    workspace_not_found: '工作区目录不存在。',
    workspace_not_allowed: '该路径不在服务允许的根目录内。',
    workspace_invalid: '工作区路径格式无效。',
    validation_error: '记忆内容不符合要求，请检查后重试。',
  }
  if (messages[code]) return messages[code]
  if (rawMessage && hasChineseText(rawMessage)) return rawMessage
  if (status === 400 || status === 422) return '记忆内容不符合要求，请检查后重试。'
  if (status === 403) return '当前工作区没有执行此记忆操作的权限。'
  if (status === 404) return '这条记忆不存在或已被删除。'
  if (status === 409) return '记忆状态已经发生变化，请刷新后重试。'
  return status > 0
    ? `记忆请求失败（HTTP ${status}），请稍后重试。`
    : '无法连接本机记忆服务，请确认后端已经启动。'
}

async function readJson(response: Response): Promise<unknown> {
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
  let candidate: unknown = payload
  if (isRecord(payload) && 'error' in payload) candidate = payload.error
  if (isRecord(payload) && 'detail' in payload) candidate = payload.detail

  const code =
    isRecord(candidate) && typeof candidate.code === 'string'
      ? candidate.code
      : status === 422
        ? 'validation_error'
        : 'request_failed'
  const rawMessage =
    isRecord(candidate) && typeof candidate.message === 'string'
      ? candidate.message
      : typeof candidate === 'string'
        ? candidate
        : null
  return { code, message: localizedMessage(code, rawMessage, status) }
}

function workspaceQuery(workspace: string): string {
  return new URLSearchParams({ workspace }).toString()
}

export function createMemoryApi(fetchImpl: FetchLike = globalThis.fetch): MemoryApi {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      if (isAbortError(error)) throw error
      throw new MemoryApiError(0, {
        code: 'network_error',
        message: localizedMessage('network_error', null, 0),
      })
    }

    const payload = await readJson(response)
    if (!response.ok) {
      throw new MemoryApiError(response.status, failureFrom(payload, response.status))
    }
    return payload as T
  }

  return {
    list: async (workspace, signal) => {
      const response = await request<{ items: MemoryEntry[] }>(
        `/api/v1/memories?${workspaceQuery(workspace)}`,
        { signal },
      )
      return response.items
    },
    create: (memory: CreateMemoryRequest, signal) =>
      request<MemoryEntry>('/api/v1/memories', {
        method: 'POST',
        body: JSON.stringify(memory),
        signal,
      }),
    update: (id, memory: UpdateMemoryRequest, signal) =>
      request<MemoryEntry>(`/api/v1/memories/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify(memory),
        signal,
      }),
    remove: async (id, workspace, signal) => {
      await request<unknown>(
        `/api/v1/memories/${encodeURIComponent(id)}?${workspaceQuery(workspace)}`,
        { method: 'DELETE', signal },
      )
    },
    purge: async (workspace, signal) => {
      const response = await request<{ deleted_count: number }>('/api/v1/memories/purge', {
        method: 'POST',
        body: JSON.stringify({ workspace }),
        signal,
      })
      return response.deleted_count
    },
  }
}

export const memoryApi = createMemoryApi()
