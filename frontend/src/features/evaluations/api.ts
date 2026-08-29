import { httpClient, type HttpClient } from '../../shared/api/http'
import type { EvaluationRun, EvaluationRunListItem } from './types'

export function createEvaluationApi(http: HttpClient = httpClient) {
  return {
    list: async (signal?: AbortSignal) => {
      const response = await http.request<{ runs: EvaluationRunListItem[] }>(
        '/api/v1/evaluations',
        { signal },
      )
      return response.runs
    },
    get: (runId: string, signal?: AbortSignal) =>
      http.request<EvaluationRun>(`/api/v1/evaluations/${encodeURIComponent(runId)}`, {
        signal,
      }),
  }
}

export const evaluationApi = createEvaluationApi()
