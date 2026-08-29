import { httpClient, type HttpClient } from '../../shared/api/http'
import type { DirectoryListing, Workspace } from './types'

export interface CreateWorkspaceInput {
  path: string
  display_name?: string
}

export function createWorkspaceApi(http: HttpClient = httpClient) {
  return {
    async list(signal?: AbortSignal): Promise<Workspace[]> {
      const result = await http.request<{ items: Workspace[] }>('/api/v1/workspaces', { signal })
      return result.items
    },
    create: (input: CreateWorkspaceInput, signal?: AbortSignal) =>
      http.request<Workspace>('/api/v1/workspaces', {
        method: 'POST',
        body: JSON.stringify(input),
        signal,
      }),
    archive: (workspaceId: string, signal?: AbortSignal) =>
      http.request<void>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}`, {
        method: 'DELETE',
        signal,
      }),
    browse: (path?: string, signal?: AbortSignal) => {
      const query = path ? `?${new URLSearchParams({ path })}` : ''
      return http.request<DirectoryListing>(`/api/v1/workspaces/browse${query}`, { signal })
    },
  }
}

export const workspaceApi = createWorkspaceApi()
