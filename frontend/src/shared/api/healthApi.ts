import { httpClient, type HttpClient } from './http'
import type { HealthResponse } from './types'

export function createHealthApi(http: HttpClient = httpClient) {
  return {
    get: (signal?: AbortSignal) =>
      http.request<HealthResponse>('/api/v1/health', { signal }),
  }
}

export const healthApi = createHealthApi()
