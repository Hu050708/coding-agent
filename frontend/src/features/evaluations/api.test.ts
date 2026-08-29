import { describe, expect, it, vi } from 'vitest'

import type { HttpClient } from '../../shared/api/http'
import { createEvaluationApi } from './api'

describe('evaluation API', () => {
  it('lists runs and encodes the selected report id', async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({ runs: [{ run_id: 'formal-3x3' }] })
      .mockResolvedValueOnce({ run_id: 'formal-3x3' })
    const api = createEvaluationApi({ request } as unknown as HttpClient)

    await api.list()
    await api.get('formal 3x3')

    expect(request).toHaveBeenNthCalledWith(1, '/api/v1/evaluations', {
      signal: undefined,
    })
    expect(request.mock.calls[1]?.[0]).toBe('/api/v1/evaluations/formal%203x3')
  })
})
