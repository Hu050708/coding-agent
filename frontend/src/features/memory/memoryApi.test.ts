import { describe, expect, it, vi } from 'vitest'

import { createMemoryApi } from './memoryApi'
import type { MemoryEntry } from './types'

function entry(overrides: Partial<MemoryEntry> = {}): MemoryEntry {
  return {
    id: 'memory/1',
    workspace: 'E:\\code\\demo',
    kind: 'decision',
    content: 'API 使用 FastAPI。',
    source: 'manual',
    source_run_id: null,
    pinned: false,
    enabled: true,
    created_at: '2026-08-27T09:00:00Z',
    updated_at: '2026-08-27T09:00:00Z',
    ...overrides,
  }
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('memoryApi', () => {
  it('lists a URL-encoded workspace and unwraps items', async () => {
    const expected = entry()
    const fetchMock = vi.fn(async (..._args: Parameters<typeof fetch>) =>
      jsonResponse({ items: [expected] }),
    )
    const api = createMemoryApi(fetchMock)

    await expect(api.list('E:\\code\\demo folder')).resolves.toEqual([expected])
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/v1/memories?workspace=E%3A%5Ccode%5Cdemo+folder',
    )
  })

  it('uses the frozen create and update request bodies', async () => {
    const fetchMock = vi.fn(async (..._args: Parameters<typeof fetch>) => jsonResponse(entry()))
    const api = createMemoryApi(fetchMock)
    const createRequest = {
      workspace: 'E:\\code\\demo',
      kind: 'fact' as const,
      content: '测试命令是 pytest。',
      pinned: true,
      source_run_id: 'run-1',
    }

    await api.create(createRequest)
    await api.update('memory/1', {
      workspace: createRequest.workspace,
      enabled: false,
      content: '测试命令为 pytest。',
    })

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/memories')
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ method: 'POST', body: JSON.stringify(createRequest) }),
    )
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/memories/memory%2F1')
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          workspace: 'E:\\code\\demo',
          enabled: false,
          content: '测试命令为 pytest。',
        }),
      }),
    )
  })

  it('deletes one workspace entry and returns the purge count', async () => {
    let requestCount = 0
    const fetchMock = vi.fn(async (..._args: Parameters<typeof fetch>) => {
      requestCount += 1
      return requestCount === 1
        ? new Response(null, { status: 204 })
        : jsonResponse({ deleted_count: 3 })
    })
    const api = createMemoryApi(fetchMock)

    await api.remove('memory/1', 'E:\\code\\demo')
    await expect(api.purge('E:\\code\\demo')).resolves.toBe(3)

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/v1/memories/memory%2F1?workspace=E%3A%5Ccode%5Cdemo',
    )
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ method: 'DELETE' }))
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ workspace: 'E:\\code\\demo' }),
      }),
    )
  })

  it('turns structured and network failures into Chinese errors', async () => {
    const deniedFetch = vi.fn(async (..._args: Parameters<typeof fetch>) =>
      jsonResponse(
        { error: { code: 'memory_workspace_mismatch', message: 'Workspace mismatch' } },
        403,
      ),
    )
    const offlineFetch = vi.fn(async (..._args: Parameters<typeof fetch>) => {
      throw new TypeError('Failed to fetch')
    })
    const busyFetch = vi.fn(async (..._args: Parameters<typeof fetch>) =>
      jsonResponse(
        { error: { code: 'memory_workspace_busy', message: 'Workspace has an active run' } },
        409,
      ),
    )

    await expect(createMemoryApi(deniedFetch).list('E:\\code')).rejects
      .toMatchObject({
        status: 403,
        code: 'memory_workspace_mismatch',
        message: '这条记忆不属于当前工作区。',
      })
    await expect(createMemoryApi(offlineFetch).list('E:\\code')).rejects
      .toMatchObject({
        status: 0,
        code: 'network_error',
        message: '无法连接本机记忆服务，请确认后端已经启动。',
      })
    await expect(
      createMemoryApi(busyFetch).create({
        workspace: 'E:\\code\\demo',
        kind: 'note',
        content: '不会在运行期间写入',
        pinned: false,
      }),
    ).rejects.toMatchObject({
      status: 409,
      code: 'memory_workspace_busy',
      message: '运行期间项目记忆只读，请在任务结束后再修改。',
    })
  })
})
