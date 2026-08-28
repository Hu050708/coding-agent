import { ref } from 'vue'
import { defineStore } from 'pinia'

import { localizedError } from '../../shared/api/http'
import type { MemoryEntry } from '../../shared/api/types'
import { memoryApi, type MemoryInput } from './memoryApi'

export const useMemoryStore = defineStore('memory', () => {
  const workspaceId = ref<string | null>(null)
  const items = ref<MemoryEntry[]>([])
  const open = ref(false)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)
  let generation = 0

  async function show(nextWorkspaceId: string): Promise<void> {
    open.value = true
    if (workspaceId.value === nextWorkspaceId && items.value.length > 0) return
    await load(nextWorkspaceId)
  }

  async function load(nextWorkspaceId: string): Promise<void> {
    const currentGeneration = ++generation
    workspaceId.value = nextWorkspaceId
    loading.value = true
    error.value = null
    try {
      const result = await memoryApi.list(nextWorkspaceId)
      if (currentGeneration === generation) items.value = result
    } catch (reason) {
      if (currentGeneration === generation) error.value = localizedError(reason)
    } finally {
      if (currentGeneration === generation) loading.value = false
    }
  }

  async function create(input: MemoryInput): Promise<boolean> {
    if (!workspaceId.value) return false
    saving.value = true
    error.value = null
    try {
      const entry = await memoryApi.create(workspaceId.value, input)
      items.value = [entry, ...items.value]
      return true
    } catch (reason) {
      error.value = localizedError(reason)
      return false
    } finally {
      saving.value = false
    }
  }

  async function update(entry: MemoryEntry, input: Partial<MemoryInput>): Promise<void> {
    if (!workspaceId.value) return
    saving.value = true
    error.value = null
    try {
      const updated = await memoryApi.update(workspaceId.value, entry.id, input)
      items.value = items.value.map((item) => (item.id === updated.id ? updated : item))
    } catch (reason) {
      error.value = localizedError(reason)
    } finally {
      saving.value = false
    }
  }

  async function remove(entry: MemoryEntry): Promise<void> {
    if (!workspaceId.value) return
    saving.value = true
    error.value = null
    try {
      await memoryApi.remove(workspaceId.value, entry.id)
      items.value = items.value.filter((item) => item.id !== entry.id)
    } catch (reason) {
      error.value = localizedError(reason)
    } finally {
      saving.value = false
    }
  }

  async function clearAll(): Promise<void> {
    if (!workspaceId.value) return
    saving.value = true
    error.value = null
    try {
      await memoryApi.clear(workspaceId.value)
      items.value = []
    } catch (reason) {
      error.value = localizedError(reason)
    } finally {
      saving.value = false
    }
  }

  function close(): void {
    open.value = false
  }

  return {
    workspaceId,
    items,
    open,
    loading,
    saving,
    error,
    show,
    load,
    create,
    update,
    remove,
    clearAll,
    close,
  }
})
