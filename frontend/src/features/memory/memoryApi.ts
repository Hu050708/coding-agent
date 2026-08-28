import { httpClient, type HttpClient } from '../../shared/api/http'
import type { MemoryEntry } from '../../shared/api/types'

export interface MemoryInput {
  kind: MemoryEntry['kind']
  content: string
  pinned: boolean
  enabled?: boolean
}

export function createMemoryApi(http: HttpClient = httpClient) {
  const base = (workspaceId: string) =>
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/memories`

  return {
    async list(workspaceId: string, signal?: AbortSignal): Promise<MemoryEntry[]> {
      const result = await http.request<{ items: MemoryEntry[] }>(base(workspaceId), { signal })
      return result.items
    },
    create: (workspaceId: string, input: MemoryInput, signal?: AbortSignal) =>
      http.request<MemoryEntry>(base(workspaceId), {
        method: 'POST',
        body: JSON.stringify(input),
        signal,
      }),
    update: (
      workspaceId: string,
      memoryId: string,
      input: Partial<MemoryInput>,
      signal?: AbortSignal,
    ) =>
      http.request<MemoryEntry>(`${base(workspaceId)}/${encodeURIComponent(memoryId)}`, {
        method: 'PATCH',
        body: JSON.stringify(input),
        signal,
      }),
    remove: (workspaceId: string, memoryId: string, signal?: AbortSignal) =>
      http.request<void>(`${base(workspaceId)}/${encodeURIComponent(memoryId)}`, {
        method: 'DELETE',
        signal,
      }),
    clear: (workspaceId: string, signal?: AbortSignal) =>
      http.request<{ deleted_count: number }>(`${base(workspaceId)}/clear`, {
        method: 'POST',
        signal,
      }),
  }
}

export const memoryApi = createMemoryApi()
