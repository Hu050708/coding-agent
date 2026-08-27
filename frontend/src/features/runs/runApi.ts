import type {
  ApiClient,
  ApiFailure,
  ApprovalDecisionResponse,
  CreateRunRequest,
  HealthResponse,
  RunSummary,
  WorkspaceValidationResponse,
} from './types'

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

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    if (response.ok) return null
    return { error: { code: 'unexpected_response', message: `服务返回 HTTP ${response.status}` } }
  }
  return response.json()
}

function readFailure(payload: unknown, status: number): ApiFailure {
  if (isRecord(payload) && isRecord(payload.error)) {
    const code = typeof payload.error.code === 'string' ? payload.error.code : 'request_failed'
    const message =
      typeof payload.error.message === 'string' ? payload.error.message : `请求失败，HTTP ${status}`
    return { code, message }
  }
  return { code: 'request_failed', message: `请求失败，HTTP ${status}` }
}

export function createApiClient(fetchImpl: FetchLike = globalThis.fetch): ApiClient {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetchImpl(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
    const payload = await readJson(response)
    if (!response.ok) throw new ApiRequestError(response.status, readFailure(payload, response.status))
    return payload as T
  }

  return {
    health: (signal) => request<HealthResponse>('/api/v1/health', { signal }),
    validateWorkspace: (workspace, signal) =>
      request<WorkspaceValidationResponse>('/api/v1/workspaces/validate', {
        method: 'POST',
        body: JSON.stringify({ workspace }),
        signal,
      }),
    createRun: (run, signal) =>
      request<RunSummary>('/api/v1/runs', {
        method: 'POST',
        body: JSON.stringify(run satisfies CreateRunRequest),
        signal,
      }),
    getRun: (runId, signal) =>
      request<RunSummary>(`/api/v1/runs/${encodeURIComponent(runId)}`, { signal }),
    cancelRun: (runId, signal) =>
      request<RunSummary>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST',
        signal,
      }),
    decideApproval: (runId, approvalId, decision, signal) =>
      request<ApprovalDecisionResponse>(
        `/api/v1/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
        {
          method: 'POST',
          body: JSON.stringify({ decision }),
          signal,
        },
      ),
  }
}

export const apiClient = createApiClient()
