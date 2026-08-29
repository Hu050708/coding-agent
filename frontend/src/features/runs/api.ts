import { httpClient, type HttpClient } from '../../shared/api/http'
import type { PermissionMode } from '../../shared/api/types'
import type { ApprovalRequest, RunSummary } from './types'

export interface CreateRunInput {
  content: string
  permission_mode: PermissionMode
  use_memory: boolean
  client_request_id: string
}

export function createRunApi(http: HttpClient = httpClient) {
  return {
    create: (conversationId: string, input: CreateRunInput, signal?: AbortSignal) =>
      http.request<RunSummary>(
        `/api/v1/conversations/${encodeURIComponent(conversationId)}/runs`,
        {
          method: 'POST',
          body: JSON.stringify(input),
          signal,
        },
      ),
    get: (runId: string, signal?: AbortSignal) =>
      http.request<RunSummary>(`/api/v1/runs/${encodeURIComponent(runId)}`, { signal }),
    cancel: (runId: string, signal?: AbortSignal) =>
      http.request<RunSummary>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST',
        signal,
      }),
    decideApproval: (
      runId: string,
      approvalId: string,
      decision: 'approve' | 'reject',
      signal?: AbortSignal,
    ) =>
      http.request<ApprovalRequest>(
        `/api/v1/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
        {
          method: 'POST',
          body: JSON.stringify({ decision }),
          signal,
        },
      ),
  }
}

export const runApi = createRunApi()
