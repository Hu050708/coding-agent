import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Workspace } from './types'
import { workspaceApi } from './api'
import { useWorkspaceStore } from './store'

vi.mock('./api', () => ({
  workspaceApi: {
    list: vi.fn(),
    create: vi.fn(),
    archive: vi.fn(),
    browse: vi.fn(),
  },
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function workspace(id: string): Workspace {
  return {
    id,
    display_name: id,
    created_at: '2026-08-27T00:00:00Z',
    updated_at: '2026-08-27T00:00:00Z',
    archived_at: null,
  }
}

describe('workspace store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(workspaceApi.list).mockReset()
  })

  it('ignores a stale list response after a newer request completes', async () => {
    const first = deferred<Workspace[]>()
    const second = deferred<Workspace[]>()
    vi.mocked(workspaceApi.list)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const store = useWorkspaceStore()
    const firstLoad = store.load()
    const secondLoad = store.load()
    second.resolve([workspace('new')])
    await secondLoad
    first.resolve([workspace('stale')])
    await firstLoad

    expect(store.items.map((item) => item.id)).toEqual(['new'])
  })
})
