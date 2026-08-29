import { describe, expect, it, vi } from 'vitest'

import type { HttpClient } from '../../shared/api/http'
import { createRunApi } from './api'

describe('run API', () => {
  it('freezes permission and memory mode in the run request', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'run-1' })
    const api = createRunApi({ request } as unknown as HttpClient)
    await api.create('conversation-1', {
      content: '修复测试',
      permission_mode: 'ask',
      use_memory: false,
      client_request_id: 'request-1',
    })
    const init = request.mock.calls[0]?.[1]
    expect(JSON.parse(String(init?.body))).toEqual({
      content: '修复测试',
      permission_mode: 'ask',
      use_memory: false,
      client_request_id: 'request-1',
    })
  })

  it('addresses approvals under a run ID', async () => {
    const request = vi.fn().mockResolvedValue({})
    const api = createRunApi({ request } as unknown as HttpClient)
    await api.decideApproval('run/1', 'approval 1', 'reject')
    expect(request.mock.calls[0]?.[0]).toBe(
      '/api/v1/runs/run%2F1/approvals/approval%201',
    )
  })
})
