import { describe, expect, it, vi } from 'vitest'

import type { HttpClient } from '../../shared/api/http'
import { createWorkspaceApi } from './api'

describe('workspace API', () => {
  it('uses IDs after the one-time path selection', async () => {
    const request = vi.fn().mockResolvedValue({ items: [] })
    const api = createWorkspaceApi({ request } as unknown as HttpClient)
    await api.list()
    expect(request).toHaveBeenCalledWith('/api/v1/workspaces', { signal: undefined })
  })

  it('encodes restricted browser paths', async () => {
    const request = vi.fn().mockResolvedValue({ entries: [] })
    const api = createWorkspaceApi({ request } as unknown as HttpClient)
    await api.browse('E:\\code\\项目')
    expect(request.mock.calls[0]?.[0]).toContain('/api/v1/workspaces/browse?path=')
    expect(request.mock.calls[0]?.[0]).not.toContain('项目')
  })
})
