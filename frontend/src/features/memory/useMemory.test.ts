import { describe, expect, it, vi } from 'vitest'

import { MemoryApiError } from './memoryApi'
import type { MemoryApi, MemoryEntry } from './types'
import { useMemory } from './useMemory'

function entry(id: string, workspace = 'E:\\code\\demo'): MemoryEntry {
  return {
    id,
    workspace,
    kind: 'note',
    content: `记忆 ${id}`,
    source: 'manual',
    source_run_id: null,
    pinned: false,
    enabled: true,
    created_at: '2026-08-27T09:00:00Z',
    updated_at: '2026-08-27T09:00:00Z',
  }
}

function deferred<T>(): {
  promise: Promise<T>
  resolve(value: T): void
} {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

function apiStub(overrides: Partial<MemoryApi> = {}): MemoryApi {
  return {
    list: vi.fn(async () => []),
    create: vi.fn(async (request) =>
      entry('created', request.workspace),
    ),
    update: vi.fn(async (id, request) => ({
      ...entry(id, request.workspace),
      pinned: request.pinned ?? false,
      enabled: request.enabled ?? true,
    })),
    remove: vi.fn(async () => undefined),
    purge: vi.fn(async () => 0),
    ...overrides,
  }
}

describe('useMemory', () => {
  it('loads and mutates only the active workspace', async () => {
    const first = entry('first')
    const api = apiStub({
      list: vi.fn(async () => [first]),
      purge: vi.fn(async () => 1),
    })
    const memory = useMemory({ api })

    await memory.load(' E:\\code\\demo ')
    const created = await memory.create({ kind: 'fact', content: '使用 Vue。', pinned: false })
    const pinned = created ? await memory.togglePinned(created) : null
    const disabled = pinned ? await memory.toggleEnabled(pinned) : null
    const removed = disabled ? await memory.remove(disabled.id) : false
    const purged = await memory.purge()

    expect(memory.state.workspace).toBe('E:\\code\\demo')
    expect(api.create).toHaveBeenCalledWith({
      workspace: 'E:\\code\\demo',
      kind: 'fact',
      content: '使用 Vue。',
      pinned: false,
    })
    expect(api.update).toHaveBeenNthCalledWith(1, 'created', {
      workspace: 'E:\\code\\demo',
      pinned: true,
    })
    expect(api.update).toHaveBeenNthCalledWith(2, 'created', {
      workspace: 'E:\\code\\demo',
      enabled: false,
    })
    expect(removed).toBe(true)
    expect(purged).toBe(1)
    expect(memory.state.items).toEqual([])
    expect(memory.state.phase).toBe('success')
    expect(memory.state.busy).toBe(false)
  })

  it('ignores a late load response from the previous workspace', async () => {
    const oldRequest = deferred<MemoryEntry[]>()
    const newRequest = deferred<MemoryEntry[]>()
    const api = apiStub({
      list: vi
        .fn()
        .mockImplementationOnce(() => oldRequest.promise)
        .mockImplementationOnce(() => newRequest.promise),
    })
    const memory = useMemory({ api })

    const loadingOld = memory.load('E:\\code\\old')
    const loadingNew = memory.load('E:\\code\\new')
    newRequest.resolve([entry('new', 'E:\\code\\new')])
    await loadingNew
    expect(memory.state.busy).toBe(false)
    oldRequest.resolve([entry('old', 'E:\\code\\old')])
    await loadingOld

    expect(memory.state.workspace).toBe('E:\\code\\new')
    expect(memory.state.items.map((item) => item.id)).toEqual(['new'])
    expect(memory.state.phase).toBe('success')
  })

  it('reset prevents an in-flight load from restoring stale data', async () => {
    const request = deferred<MemoryEntry[]>()
    const memory = useMemory({ api: apiStub({ list: vi.fn(() => request.promise) }) })

    const loading = memory.load('E:\\code\\demo')
    memory.reset()
    request.resolve([entry('late')])
    await loading

    expect(memory.state).toMatchObject({
      phase: 'idle',
      workspace: '',
      items: [],
      message: null,
      busy: false,
    })
  })

  it('returns safe values and a Chinese message instead of rejecting to UI', async () => {
    const failure = new MemoryApiError(503, {
      code: 'memory_store_unavailable',
      message: '记忆存储暂时不可用，本次操作没有完成。',
    })
    const api = apiStub({
      create: vi.fn(async () => {
        throw failure
      }),
      remove: vi.fn(async () => {
        throw new Error('database unavailable')
      }),
      purge: vi.fn(async () => {
        throw failure
      }),
    })
    const memory = useMemory({ api })
    await memory.load('E:\\code\\demo')

    await expect(
      memory.create({ kind: 'note', content: '不会保存', pinned: false }),
    ).resolves.toBeNull()
    expect(memory.state.message).toBe('记忆存储暂时不可用，本次操作没有完成。')
    await expect(memory.remove('missing')).resolves.toBe(false)
    expect(memory.state.message).toBe('记忆操作未能完成，请确认后端服务正常后重试。')
    await expect(memory.purge()).resolves.toBeNull()
    expect(memory.state.busy).toBe(false)
  })
})
