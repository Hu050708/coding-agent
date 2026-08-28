import { describe, expect, it, vi } from 'vitest'

import { ApiRequestError, createHttpClient, localizedError } from './http'

describe('http client', () => {
  it('reads structured FastAPI errors without exposing arbitrary payloads', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: { code: 'workspace_busy', message: 'raw provider message' } }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const request = createHttpClient(fetchMock).request('/api/v1/test')
    await expect(request).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 409,
      code: 'workspace_busy',
    })
  })

  it('localizes recoverable service states', () => {
    expect(
      localizedError(
        new ApiRequestError(503, { code: 'database_unavailable', message: 'db failed' }),
      ),
    ).toContain('coding-agent-postgres')
  })

  it('normalizes network failures', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(new Error('socket detail'))
    await expect(createHttpClient(fetchMock).request('/api/v1/test')).rejects.toBeInstanceOf(
      TypeError,
    )
  })
})
