import { httpClient, type HttpClient } from '../../shared/api/http'
import type { ChatMessage, Conversation, PermissionMode } from '../../shared/api/types'

export interface CreateConversationInput {
  workspace_id: string
  title?: string
  default_permission_mode: PermissionMode
  use_memory: boolean
}

export interface UpdateConversationInput {
  title?: string
  default_permission_mode?: PermissionMode
  use_memory?: boolean
}

export function createConversationApi(http: HttpClient = httpClient) {
  return {
    async list(workspaceId: string, signal?: AbortSignal): Promise<Conversation[]> {
      const query = new URLSearchParams({ workspace_id: workspaceId })
      const result = await http.request<{ items: Conversation[] }>(
        `/api/v1/conversations?${query}`,
        { signal },
      )
      return result.items
    },
    create: (input: CreateConversationInput, signal?: AbortSignal) =>
      http.request<Conversation>('/api/v1/conversations', {
        method: 'POST',
        body: JSON.stringify(input),
        signal,
      }),
    get: (conversationId: string, signal?: AbortSignal) =>
      http.request<Conversation>(`/api/v1/conversations/${encodeURIComponent(conversationId)}`, {
        signal,
      }),
    update: (
      conversationId: string,
      input: UpdateConversationInput,
      signal?: AbortSignal,
    ) =>
      http.request<Conversation>(`/api/v1/conversations/${encodeURIComponent(conversationId)}`, {
        method: 'PATCH',
        body: JSON.stringify(input),
        signal,
      }),
    archive: (conversationId: string, signal?: AbortSignal) =>
      http.request<void>(`/api/v1/conversations/${encodeURIComponent(conversationId)}`, {
        method: 'DELETE',
        signal,
      }),
    async messages(conversationId: string, signal?: AbortSignal): Promise<ChatMessage[]> {
      const result = await http.request<{ items: ChatMessage[] }>(
        `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
        { signal },
      )
      return result.items
    },
  }
}

export const conversationApi = createConversationApi()
