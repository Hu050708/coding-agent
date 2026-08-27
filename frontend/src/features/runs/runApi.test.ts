import { describe, expect, it, vi } from 'vitest'

import { createApiClient } from './runApi'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  it('uses the frozen workspace validation contract', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ valid: true, workspace: 'E:\\code\\demo', allowed_root: 'E:\\code' }),
    )
    const client = createApiClient(fetchMock as unknown as typeof fetch)

    const result = await client.validateWorkspace('E:\\code\\demo')

    expect(result.valid).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/workspaces/validate',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ workspace: 'E:\\code\\demo' }),
      }),
    )
  })

  it('preserves structured backend errors', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ error: { code: 'workspace_denied', message: '路径不在允许范围内' } }, 403),
    )
    const client = createApiClient(fetchMock as unknown as typeof fetch)

    await expect(client.validateWorkspace('C:\\Windows')).rejects.toMatchObject({
      status: 403,
      code: 'workspace_denied',
      message: '路径不在允许范围内',
    })
  })

  it('sends the explicit project-memory choice when a run starts', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ run_id: 'run-1' }))
    const client = createApiClient(fetchMock as unknown as typeof fetch)

    await client.createRun({
      workspace: 'E:\\code\\demo',
      task: '检查边界',
      use_memory: false,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/runs',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          workspace: 'E:\\code\\demo',
          task: '检查边界',
          use_memory: false,
        }),
      }),
    )
  })

  it('encodes run and approval identifiers in endpoint paths', async () => {
    const fetchMock = vi.fn(async (..._args: Parameters<typeof fetch>) =>
      jsonResponse({ run_id: 'run/1', approval_id: 'approval 1', decision: 'approve', accepted: true }),
    )
    const client = createApiClient(fetchMock as unknown as typeof fetch)

    await client.decideApproval('run/1', 'approval 1', 'approve')

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/runs/run%2F1/approvals/approval%201')
  })
})
