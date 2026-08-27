import { reactive } from 'vue'

import { memoryApi, MemoryApiError } from './memoryApi'
import type {
  CreateMemoryInput,
  MemoryApi,
  MemoryEntry,
  MemoryState,
  UpdateMemoryInput,
} from './types'

export interface MemoryDependencies {
  api?: MemoryApi
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

function errorMessage(error: unknown): string {
  if (error instanceof MemoryApiError) return error.message
  return '记忆操作未能完成，请确认后端服务正常后重试。'
}

export function useMemory(dependencies: MemoryDependencies = {}) {
  const api = dependencies.api ?? memoryApi
  const state = reactive<MemoryState>({
    phase: 'idle',
    workspace: '',
    items: [],
    message: null,
    busy: false,
  })

  const pending = new Set<symbol>()
  let loadSequence = 0
  let workspaceVersion = 0
  let activeLoad: AbortController | null = null
  let activeLoadToken: symbol | null = null

  function syncBusy(): void {
    state.busy = pending.size > 0
  }

  function beginOperation(): symbol {
    const token = Symbol('memory-operation')
    pending.add(token)
    syncBusy()
    return token
  }

  function endOperation(token: symbol): void {
    pending.delete(token)
    syncBusy()
  }

  function isCurrent(version: number, workspace: string): boolean {
    return workspaceVersion === version && state.workspace === workspace
  }

  function setError(error: unknown): void {
    state.phase = 'error'
    state.message = errorMessage(error)
  }

  function currentContext(): { workspace: string; version: number } | null {
    const workspace = state.workspace.trim()
    if (workspace) return { workspace, version: workspaceVersion }
    state.phase = 'error'
    state.message = '请先选择工作区，再管理项目记忆。'
    return null
  }

  function reset(): void {
    loadSequence += 1
    workspaceVersion += 1
    activeLoad?.abort()
    activeLoad = null
    activeLoadToken = null
    pending.clear()
    Object.assign(state, {
      phase: 'idle',
      workspace: '',
      items: [],
      message: null,
      busy: false,
    } satisfies MemoryState)
  }

  async function load(workspaceValue: string): Promise<void> {
    const workspace = workspaceValue.trim()
    const sequence = ++loadSequence
    activeLoad?.abort()
    activeLoad = null
    if (activeLoadToken) pending.delete(activeLoadToken)
    activeLoadToken = null
    syncBusy()

    if (!workspace) {
      if (state.workspace) workspaceVersion += 1
      state.workspace = ''
      state.items = []
      state.phase = 'error'
      state.message = '请先选择要读取记忆的工作区。'
      return
    }

    if (state.workspace !== workspace) workspaceVersion += 1
    const version = workspaceVersion
    state.workspace = workspace
    state.items = []
    state.phase = 'loading'
    state.message = null

    const controller = new AbortController()
    const token = beginOperation()
    activeLoad = controller
    activeLoadToken = token
    try {
      const items = await api.list(workspace, controller.signal)
      if (sequence !== loadSequence || !isCurrent(version, workspace)) return
      state.items = items
      state.phase = 'success'
    } catch (error) {
      if (sequence !== loadSequence || !isCurrent(version, workspace) || isAbortError(error)) return
      setError(error)
    } finally {
      if (activeLoad === controller) {
        activeLoad = null
        activeLoadToken = null
      }
      endOperation(token)
    }
  }

  async function create(input: CreateMemoryInput): Promise<MemoryEntry | null> {
    const context = currentContext()
    if (!context) return null
    const token = beginOperation()
    state.message = null
    try {
      const entry = await api.create({ ...input, workspace: context.workspace })
      if (isCurrent(context.version, context.workspace)) {
        state.items = [entry, ...state.items.filter((item) => item.id !== entry.id)]
        state.phase = 'success'
      }
      return entry
    } catch (error) {
      if (isCurrent(context.version, context.workspace)) setError(error)
      return null
    } finally {
      endOperation(token)
    }
  }

  async function update(id: string, changes: UpdateMemoryInput): Promise<MemoryEntry | null> {
    const context = currentContext()
    if (!context) return null
    const token = beginOperation()
    state.message = null
    try {
      const entry = await api.update(id, { ...changes, workspace: context.workspace })
      if (isCurrent(context.version, context.workspace)) {
        state.items = state.items.map((item) => (item.id === entry.id ? entry : item))
        state.phase = 'success'
      }
      return entry
    } catch (error) {
      if (isCurrent(context.version, context.workspace)) setError(error)
      return null
    } finally {
      endOperation(token)
    }
  }

  function togglePinned(entry: MemoryEntry): Promise<MemoryEntry | null> {
    return update(entry.id, { pinned: !entry.pinned })
  }

  function toggleEnabled(entry: MemoryEntry): Promise<MemoryEntry | null> {
    return update(entry.id, { enabled: !entry.enabled })
  }

  async function remove(id: string): Promise<boolean> {
    const context = currentContext()
    if (!context) return false
    const token = beginOperation()
    state.message = null
    try {
      await api.remove(id, context.workspace)
      if (isCurrent(context.version, context.workspace)) {
        state.items = state.items.filter((item) => item.id !== id)
        state.phase = 'success'
      }
      return true
    } catch (error) {
      if (isCurrent(context.version, context.workspace)) setError(error)
      return false
    } finally {
      endOperation(token)
    }
  }

  async function purge(): Promise<number | null> {
    const context = currentContext()
    if (!context) return null
    const token = beginOperation()
    state.message = null
    try {
      const deletedCount = await api.purge(context.workspace)
      if (isCurrent(context.version, context.workspace)) {
        state.items = []
        state.phase = 'success'
      }
      return deletedCount
    } catch (error) {
      if (isCurrent(context.version, context.workspace)) setError(error)
      return null
    } finally {
      endOperation(token)
    }
  }

  return {
    state,
    load,
    reset,
    create,
    update,
    togglePinned,
    toggleEnabled,
    remove,
    purge,
  }
}
