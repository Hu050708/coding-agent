import { describe, expect, it, vi } from 'vitest'

import type { HttpClient } from '../../shared/api/http'
import { createConversationApi } from './api'

describe('conversation API', () => {
  it('lists conversations by workspace ID rather than a filesystem path', async () => {
    const request = vi.fn().mockResolvedValue({ items: [] })
    const api = createConversationApi({ request } as unknown as HttpClient)
    await api.list('workspace/one')
    expect(request.mock.calls[0]?.[0]).toBe(
      '/api/v1/conversations?workspace_id=workspace%2Fone',
    )
  })

  it('loads visible messages from the conversation resource', async () => {
    const request = vi.fn().mockResolvedValue({ items: [] })
    const api = createConversationApi({ request } as unknown as HttpClient)
    await api.messages('conversation one')
    expect(request.mock.calls[0]?.[0]).toBe(
      '/api/v1/conversations/conversation%20one/messages',
    )
  })
})
