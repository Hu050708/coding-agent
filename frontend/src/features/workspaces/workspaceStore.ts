import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { localizedError } from '../../shared/api/http'
import type { Workspace } from '../../shared/api/types'
import { workspaceApi } from './workspaceApi'

export const useWorkspaceStore = defineStore('workspaces', () => {
  const items = ref<Workspace[]>([])
  const selectedId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let generation = 0

  const selected = computed(
    () => items.value.find((workspace) => workspace.id === selectedId.value) ?? null,
  )

  async function load(): Promise<void> {
    const current = ++generation
    loading.value = true
    error.value = null
    try {
      const result = await workspaceApi.list()
      if (current !== generation) return
      items.value = result
      if (selectedId.value && !result.some((item) => item.id === selectedId.value)) {
        selectedId.value = null
      }
    } catch (reason) {
      if (current === generation) error.value = localizedError(reason)
    } finally {
      if (current === generation) loading.value = false
    }
  }

  async function create(path: string, displayName?: string): Promise<Workspace | null> {
    error.value = null
    try {
      const workspace = await workspaceApi.create({
        path,
        ...(displayName?.trim() ? { display_name: displayName.trim() } : {}),
      })
      items.value = [workspace, ...items.value.filter((item) => item.id !== workspace.id)]
      selectedId.value = workspace.id
      return workspace
    } catch (reason) {
      error.value = localizedError(reason)
      return null
    }
  }

  function select(workspaceId: string | null): void {
    selectedId.value = workspaceId
  }

  return { items, selectedId, selected, loading, error, load, create, select }
})
